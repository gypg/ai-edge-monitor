"""Model validation pipeline for deployment readiness.

Checks:
- Model file exists and is readable
- File format matches expected extension
- File size within reasonable bounds
- ONNX model structure validation (when onnxruntime available)
- TensorRT engine compatibility check
- Input/output shape validation
- Quantization format detection

Python 3.8+ compatible.  No required external dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional runtime imports (mirrors onnx_bridge / tensorrt_bridge pattern)
# ---------------------------------------------------------------------------

try:
    import onnxruntime as ort

    HAS_ORT = True
except ImportError:
    HAS_ORT = False

try:
    import tensorrt as trt

    HAS_TENSORRT = True
except ImportError:
    HAS_TENSORRT = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ONNX_EXTENSIONS = (".onnx",)
_TRT_EXTENSIONS = (".engine", ".trt", ".plan")

# File-size bounds (bytes).  Anything outside this range is a warning.
_MIN_MODEL_SIZE = 100  # < 100 bytes is almost certainly not a real model
_MAX_MODEL_SIZE = 10 * 1024 * 1024 * 1024  # 10 GiB — generous upper bound

# ONNX magic bytes: protobuf outer message starts with field 1 (ModelProto)
# which is a length-delimited field (wire type 2).  First bytes vary, but the
# file always starts with a valid protobuf tag.  We use a lighter heuristic:
# check that the file contains "ir_version" or is valid protobuf.
_ONNX_MAGIC = b"\x08"  # common first byte for ONNX (protobuf field 1, varint)

# TensorRT engine files often start with a version-specific header.
# We rely on file extension + size heuristic rather than magic bytes because
# the header format changes across TRT versions.

# Quantization keywords detected in file metadata or filename
_QUANT_KEYWORDS = {
    "int8": "INT8",
    "uint8": "UINT8",
    "fp16": "FP16",
    "float16": "FP16",
    "half": "FP16",
    "bf16": "BF16",
    "bfloat16": "BF16",
    "int4": "INT4",
    "fp8": "FP8",
    "e4m3": "FP8",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class CheckStatus(str, Enum):
    """Outcome of a single validation check."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class CheckResult:
    """Result of one validation step."""

    name: str
    status: CheckStatus
    message: str


@dataclass
class ValidationResult:
    """Aggregate result of a full model validation run.

    Attributes:
        overall_status: The worst status across all checks.
        checks: Individual check results in execution order.
        model_path: Absolute path to the validated model.
        model_format: Detected format (``"onnx"``, ``"tensorrt"``, ``"unknown"``).
        file_size_bytes: Size of the model file.
        quantization: Detected quantization label, or ``None``.
        input_info: Input tensor metadata when discoverable.
        output_info: Output tensor metadata when discoverable.
    """

    overall_status: CheckStatus
    checks: List[CheckResult]
    model_path: str
    model_format: str
    file_size_bytes: int
    quantization: Optional[str]
    input_info: Optional[Dict[str, Any]]
    output_info: Optional[Dict[str, Any]]


@dataclass
class InferenceRequirements:
    """Estimated resources needed to run the model.

    These are heuristic estimates derived from file size and metadata -- they
    do **not** require loading the model into a runtime.
    """

    estimated_memory_bytes: int
    estimated_params_millions: float
    recommended_batch_size: int
    recommended_dtype: str


# ---------------------------------------------------------------------------
# Helpers (pure functions, easy to test)
# ---------------------------------------------------------------------------


def _detect_format(model_path: str) -> str:
    """Return ``"onnx"``, ``"tensorrt"``, or ``"unknown"`` based on extension."""
    lower = model_path.lower()
    if any(lower.endswith(ext) for ext in _ONNX_EXTENSIONS):
        return "onnx"
    if any(lower.endswith(ext) for ext in _TRT_EXTENSIONS):
        return "tensorrt"
    return "unknown"


def _detect_quantization(
    model_path: str, metadata: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """Heuristic quantization detection from filename and optional metadata."""
    lower = model_path.lower()
    for keyword, label in _QUANT_KEYWORDS.items():
        if keyword in lower:
            return label

    if metadata is not None:
        meta_str = json.dumps(metadata).lower()
        for keyword, label in _QUANT_KEYWORDS.items():
            if keyword in meta_str:
                return label

    return None


def _estimate_memory(file_size_bytes: int, fmt: str) -> int:
    """Estimate runtime memory from file size and format.

    Heuristic rules:
    - ONNX: runtime memory ~= 2-3x file size (weights + activations buffer)
    - TensorRT: runtime memory ~= 1.5x file size (already optimized)
    - Unknown: 2x file size
    """
    if fmt == "onnx":
        return int(file_size_bytes * 2.5)
    if fmt == "tensorrt":
        return int(file_size_bytes * 1.5)
    return int(file_size_bytes * 2.0)


def _estimate_params_millions(file_size_bytes: int, fmt: str) -> float:
    """Rough parameter count estimate.

    For FP32 models: 4 bytes per parameter.  FP16: 2 bytes.  TRT engines
    are mixed-precision so we assume ~3 bytes/param on average.
    """
    if fmt == "onnx":
        # Assume FP32 weights dominate
        return round(file_size_bytes / (4 * 1_000_000), 2)
    if fmt == "tensorrt":
        # Mixed precision
        return round(file_size_bytes / (3 * 1_000_000), 2)
    return round(file_size_bytes / (4 * 1_000_000), 2)


# ---------------------------------------------------------------------------
# ModelValidator
# ---------------------------------------------------------------------------


class ModelValidator:
    """Validate an ONNX or TensorRT model for deployment readiness.

    Usage::

        validator = ModelValidator()
        result = validator.validate("model.onnx", expected_input_shape=(1, 3, 224, 224))
        print(result.overall_status)

    All checks degrade gracefully -- missing runtimes produce WARN rather
    than FAIL so that validation can still report useful information on
    machines without GPU SDKs installed.
    """

    def validate(
        self,
        model_path: str,
        expected_input_shape: Optional[Tuple[int, ...]] = None,
    ) -> ValidationResult:
        """Run the full validation pipeline on *model_path*.

        Args:
            model_path: Filesystem path to the model file.
            expected_input_shape: Optional NCHW (or similar) shape to check
                against the model's declared inputs.

        Returns:
            A ``ValidationResult`` with per-check details.
        """
        checks: List[CheckResult] = []
        model_format = "unknown"
        file_size = 0
        quantization: Optional[str] = None
        input_info: Optional[Dict[str, Any]] = None
        output_info: Optional[Dict[str, Any]] = None

        # -- 1. File existence & readability --------------------------------
        check = self._check_file_exists(model_path)
        checks.append(check)
        if check.status == CheckStatus.FAIL:
            return self._build_result(
                checks,
                model_path,
                "unknown",
                0,
                None,
                None,
                None,
            )

        # -- 2. File size ---------------------------------------------------
        file_size = os.path.getsize(model_path)
        checks.append(self._check_file_size(file_size))

        # -- 3. Format detection --------------------------------------------
        fmt_check, model_format = self._check_format(model_path)
        checks.append(fmt_check)

        # -- 4. Format-specific structural validation -----------------------
        if model_format == "onnx":
            onnx_checks, input_info, output_info = self._validate_onnx_model(model_path)
            checks.extend(onnx_checks)
        elif model_format == "tensorrt":
            trt_checks = self._validate_tensorrt_engine(model_path)
            checks.extend(trt_checks)

        # -- 5. Input/output shape validation (if expected shape given) ------
        if expected_input_shape is not None and input_info is not None:
            checks.append(self._check_input_shape(input_info, expected_input_shape))

        # -- 6. Quantization detection --------------------------------------
        metadata = None
        if input_info is not None:
            metadata = {"input": input_info, "output": output_info}
        quantization = _detect_quantization(model_path, metadata)
        if quantization is not None:
            checks.append(
                CheckResult(
                    name="quantization_detection",
                    status=CheckStatus.PASS,
                    message=f"Detected quantization: {quantization}",
                )
            )

        return self._build_result(
            checks,
            model_path,
            model_format,
            file_size,
            quantization,
            input_info,
            output_info,
        )

    # ------------------------------------------------------------------
    # ONNX validation
    # ------------------------------------------------------------------

    def _validate_onnx_model(
        self,
        model_path: str,
    ) -> Tuple[List[CheckResult], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Validate ONNX model structure.

        Returns (checks, input_info, output_info).
        """
        checks: List[CheckResult] = []
        input_info: Optional[Dict[str, Any]] = None
        output_info: Optional[Dict[str, Any]] = None

        if not HAS_ORT:
            checks.append(
                CheckResult(
                    name="onnx_structure",
                    status=CheckStatus.WARN,
                    message="onnxruntime not available; skipping structural validation",
                )
            )
            return checks, None, None

        try:
            sess_opts = ort.SessionOptions()
            sess_opts.log_severity_level = 3  # suppress ORT warnings
            session = ort.InferenceSession(model_path, sess_opts)

            # Extract input metadata
            inputs = session.get_inputs()
            outputs = session.get_outputs()

            if len(inputs) == 0:
                checks.append(
                    CheckResult(
                        name="onnx_structure",
                        status=CheckStatus.FAIL,
                        message="ONNX model has no inputs",
                    )
                )
            else:
                first_input = inputs[0]
                input_info = {
                    "name": first_input.name,
                    "shape": list(first_input.shape) if hasattr(first_input, "shape") else None,
                    "dtype": str(first_input.type) if hasattr(first_input, "type") else None,
                }
                if len(inputs) > 1:
                    input_info["all_input_names"] = [inp.name for inp in inputs]

                output_names = [o.name for o in outputs]
                output_shapes = [list(o.shape) if hasattr(o, "shape") else None for o in outputs]
                output_info = {
                    "names": output_names,
                    "shapes": output_shapes,
                }

                checks.append(
                    CheckResult(
                        name="onnx_structure",
                        status=CheckStatus.PASS,
                        message=(
                            f"ONNX model valid: {len(inputs)} input(s), "
                            f"{len(outputs)} output(s)"
                        ),
                    )
                )

        except Exception as exc:
            checks.append(
                CheckResult(
                    name="onnx_structure",
                    status=CheckStatus.FAIL,
                    message=f"Failed to load ONNX model: {exc}",
                )
            )

        return checks, input_info, output_info

    # ------------------------------------------------------------------
    # TensorRT validation
    # ------------------------------------------------------------------

    def _validate_tensorrt_engine(self, model_path: str) -> List[CheckResult]:
        """Validate TensorRT engine file."""
        checks: List[CheckResult] = []

        if not HAS_TENSORRT:
            # Without TRT we can only do a basic size/magic check
            checks.append(
                CheckResult(
                    name="trt_engine",
                    status=CheckStatus.WARN,
                    message="tensorrt not available; performing basic file checks only",
                )
            )
            # Verify file is not empty / truncated
            file_size = os.path.getsize(model_path)
            if file_size < 256:
                checks.append(
                    CheckResult(
                        name="trt_engine_size",
                        status=CheckStatus.FAIL,
                        message=f"TRT engine file is suspiciously small ({file_size} bytes)",
                    )
                )
            return checks

        try:
            with open(model_path, "rb") as fh:
                header = fh.read(64)

            runtime = trt.Runtime(trt.Logger(trt.Logger.WARNING))
            engine_bytes = open(model_path, "rb").read()
            engine = runtime.deserialize_cuda_engine(engine_bytes)

            if engine is None:
                checks.append(
                    CheckResult(
                        name="trt_engine",
                        status=CheckStatus.FAIL,
                        message="Failed to deserialize TensorRT engine",
                    )
                )
            else:
                num_bindings = engine.num_io_tensors
                checks.append(
                    CheckResult(
                        name="trt_engine",
                        status=CheckStatus.PASS,
                        message=f"TensorRT engine valid: {num_bindings} I/O tensor(s)",
                    )
                )
        except Exception as exc:
            checks.append(
                CheckResult(
                    name="trt_engine",
                    status=CheckStatus.FAIL,
                    message=f"Failed to validate TRT engine: {exc}",
                )
            )

        return checks

    # ------------------------------------------------------------------
    # Individual checks (static / class helpers)
    # ------------------------------------------------------------------

    @staticmethod
    def _check_file_exists(model_path: str) -> CheckResult:
        if not os.path.exists(model_path):
            return CheckResult(
                name="file_exists",
                status=CheckStatus.FAIL,
                message=f"Model file not found: {model_path}",
            )
        if not os.path.isfile(model_path):
            return CheckResult(
                name="file_exists",
                status=CheckStatus.FAIL,
                message=f"Path is not a regular file: {model_path}",
            )
        if not os.access(model_path, os.R_OK):
            return CheckResult(
                name="file_exists",
                status=CheckStatus.FAIL,
                message=f"Model file is not readable: {model_path}",
            )
        return CheckResult(
            name="file_exists",
            status=CheckStatus.PASS,
            message="Model file exists and is readable",
        )

    @staticmethod
    def _check_file_size(file_size: int) -> CheckResult:
        if file_size < _MIN_MODEL_SIZE:
            return CheckResult(
                name="file_size",
                status=CheckStatus.FAIL,
                message=f"File too small ({file_size} bytes) -- likely not a valid model",
            )
        if file_size > _MAX_MODEL_SIZE:
            return CheckResult(
                name="file_size",
                status=CheckStatus.WARN,
                message=f"File very large ({file_size} bytes) -- may exceed deployment limits",
            )
        return CheckResult(
            name="file_size",
            status=CheckStatus.PASS,
            message=f"File size OK ({file_size} bytes)",
        )

    @staticmethod
    def _check_format(model_path: str) -> Tuple[CheckResult, str]:
        fmt = _detect_format(model_path)
        if fmt == "unknown":
            return (
                CheckResult(
                    name="format_detection",
                    status=CheckStatus.WARN,
                    message=f"Unrecognized model format for: {model_path}",
                ),
                fmt,
            )
        return (
            CheckResult(
                name="format_detection",
                status=CheckStatus.PASS,
                message=f"Detected format: {fmt}",
            ),
            fmt,
        )

    @staticmethod
    def _check_input_shape(
        input_info: Dict[str, Any],
        expected: Tuple[int, ...],
    ) -> CheckResult:
        """Compare actual model input shape against expected shape."""
        actual = input_info.get("shape")
        if actual is None:
            return CheckResult(
                name="input_shape",
                status=CheckStatus.WARN,
                message="Could not determine input shape from model metadata",
            )

        # Compare element-by-element, treating string dims (e.g. "batch_size")
        # as dynamic and thus compatible with any int.
        if len(actual) != len(expected):
            return CheckResult(
                name="input_shape",
                status=CheckStatus.FAIL,
                message=(
                    f"Shape rank mismatch: expected {len(expected)}D "
                    f"{list(expected)}, got {len(actual)}D {actual}"
                ),
            )

        mismatches: List[str] = []
        for i, (a, e) in enumerate(zip(actual, expected)):
            if isinstance(a, str):
                # dynamic dimension — always compatible
                continue
            try:
                if int(a) != e:
                    mismatches.append(f"dim {i}: expected {e}, got {a}")
            except (TypeError, ValueError):
                # non-integer dim (e.g. None) — dynamic, ok
                continue

        if mismatches:
            return CheckResult(
                name="input_shape",
                status=CheckStatus.FAIL,
                message=f"Input shape mismatch: {'; '.join(mismatches)}",
            )

        return CheckResult(
            name="input_shape",
            status=CheckStatus.PASS,
            message=f"Input shape matches expected {list(expected)}",
        )

    # ------------------------------------------------------------------
    # Inference requirements estimation
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_inference_requirements(model_path: str) -> InferenceRequirements:
        """Estimate runtime resource needs from the model file.

        Does **not** load the model -- uses file size heuristics.
        """
        file_size = os.path.getsize(model_path)
        fmt = _detect_format(model_path)

        mem = _estimate_memory(file_size, fmt)
        params = _estimate_params_millions(file_size, fmt)

        # Heuristic batch-size recommendation: larger models get batch=1
        if params > 500:
            batch = 1
        elif params > 100:
            batch = 4
        else:
            batch = 8

        # Recommended dtype based on detected quantization
        quant = _detect_quantization(model_path)
        if quant in ("INT8", "UINT8"):
            dtype = "int8"
        elif quant in ("FP16", "BF16"):
            dtype = "float16"
        else:
            dtype = "float32"

        return InferenceRequirements(
            estimated_memory_bytes=mem,
            estimated_params_millions=params,
            recommended_batch_size=batch,
            recommended_dtype=dtype,
        )

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    @staticmethod
    def generate_validation_report(
        result: ValidationResult,
        *,
        fmt: str = "json",
    ) -> str:
        """Render a human-readable or JSON report from a ``ValidationResult``.

        Args:
            result: The validation result to format.
            fmt: ``"json"`` for structured JSON, ``"text"`` for plain text.

        Returns:
            The formatted report string.
        """
        if fmt == "json":
            return ModelValidator._report_json(result)
        if fmt == "text":
            return ModelValidator._report_text(result)
        raise ValueError(f"Unsupported report format: {fmt!r} (use 'json' or 'text')")

    @staticmethod
    def _report_json(result: ValidationResult) -> str:
        payload: Dict[str, Any] = {
            "overall_status": result.overall_status.value,
            "model_path": result.model_path,
            "model_format": result.model_format,
            "file_size_bytes": result.file_size_bytes,
            "quantization": result.quantization,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                }
                for c in result.checks
            ],
        }
        if result.input_info is not None:
            payload["input_info"] = result.input_info
        if result.output_info is not None:
            payload["output_info"] = result.output_info
        return json.dumps(payload, indent=2)

    @staticmethod
    def _report_text(result: ValidationResult) -> str:
        lines = [
            "=" * 60,
            "  MODEL VALIDATION REPORT",
            "=" * 60,
            f"  Path      : {result.model_path}",
            f"  Format    : {result.model_format}",
            f"  Size      : {result.file_size_bytes:,} bytes",
            f"  Quant     : {result.quantization or 'N/A'}",
            f"  Status    : {result.overall_status.value.upper()}",
            "-" * 60,
            "  Checks:",
        ]
        for c in result.checks:
            icon = {"pass": "[PASS]", "warn": "[WARN]", "fail": "[FAIL]"}.get(
                c.status.value, "[????]"
            )
            lines.append(f"    {icon} {c.name}: {c.message}")
        if result.input_info:
            lines.append("-" * 60)
            lines.append(f"  Input : {result.input_info}")
        if result.output_info:
            lines.append(f"  Output: {result.output_info}")
        lines.append("=" * 60)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_result(
        checks: List[CheckResult],
        model_path: str,
        model_format: str,
        file_size: int,
        quantization: Optional[str],
        input_info: Optional[Dict[str, Any]],
        output_info: Optional[Dict[str, Any]],
    ) -> ValidationResult:
        """Derive overall status and assemble ``ValidationResult``."""
        priority = {CheckStatus.FAIL: 0, CheckStatus.WARN: 1, CheckStatus.PASS: 2}
        worst = CheckStatus.PASS
        for c in checks:
            if priority[c.status] < priority[worst]:
                worst = c.status
        return ValidationResult(
            overall_status=worst,
            checks=checks,
            model_path=os.path.abspath(model_path),
            model_format=model_format,
            file_size_bytes=file_size,
            quantization=quantization,
            input_info=input_info,
            output_info=output_info,
        )
