"""Tests for the model validation pipeline (Python 3.8+).

Covers:
- File existence / readability checks
- File size boundary conditions
- Format detection (ONNX, TensorRT, unknown)
- Quantization detection heuristics
- Input/output shape comparison
- Inference requirements estimation
- Report generation (JSON and text)
- Graceful degradation when runtimes are missing
- Full pipeline integration with mock model files

Run: ``python tests/inference_monitor/test_model_validator.py``
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

# ---------------------------------------------------------------------------
# Ensure ``src/`` is on sys.path (same pattern as test_tensorrt.py)
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from inference_monitor.model_validator import (
    CheckResult,
    CheckStatus,
    InferenceRequirements,
    ModelValidator,
    ValidationResult,
    _detect_format,
    _detect_quantization,
    _estimate_memory,
    _estimate_params_millions,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_temp_file(suffix: str, content: bytes = b"\x00" * 1024) -> str:
    """Create a temporary file with *content* and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, content)
    os.close(fd)
    return path


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Tests -- file existence and readability
# ---------------------------------------------------------------------------


class TestFileExistenceChecks(unittest.TestCase):
    """Validate _check_file_exists behaviour."""

    def test_missing_file_returns_fail(self) -> None:
        result = ModelValidator._check_file_exists("/nonexistent/model.onnx")
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertIn("not found", result.message)

    def test_existing_readable_file_returns_pass(self) -> None:
        path = _make_temp_file(".onnx")
        try:
            result = ModelValidator._check_file_exists(path)
            self.assertEqual(result.status, CheckStatus.PASS)
        finally:
            _cleanup(path)

    def test_directory_returns_fail(self) -> None:
        td = tempfile.mkdtemp()
        try:
            result = ModelValidator._check_file_exists(td)
            self.assertEqual(result.status, CheckStatus.FAIL)
            self.assertIn("not a regular file", result.message)
        finally:
            os.rmdir(td)


# ---------------------------------------------------------------------------
# Tests -- file size
# ---------------------------------------------------------------------------


class TestFileSizeChecks(unittest.TestCase):
    """Validate _check_file_size boundary conditions."""

    def test_zero_bytes_returns_fail(self) -> None:
        result = ModelValidator._check_file_size(0)
        self.assertEqual(result.status, CheckStatus.FAIL)

    def test_too_small_returns_fail(self) -> None:
        result = ModelValidator._check_file_size(10)  # < 100
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertIn("too small", result.message.lower())

    def test_normal_size_returns_pass(self) -> None:
        result = ModelValidator._check_file_size(50_000_000)  # ~50 MB
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_very_large_returns_warn(self) -> None:
        result = ModelValidator._check_file_size(20 * 1024 * 1024 * 1024)  # 20 GiB
        self.assertEqual(result.status, CheckStatus.WARN)


# ---------------------------------------------------------------------------
# Tests -- format detection
# ---------------------------------------------------------------------------


class TestFormatDetection(unittest.TestCase):
    """Verify extension-based format identification."""

    def test_onnx_extension(self) -> None:
        self.assertEqual(_detect_format("model.onnx"), "onnx")
        self.assertEqual(_detect_format("/path/to/MODEL.Onnx"), "onnx")

    def test_trt_extensions(self) -> None:
        for ext in (".engine", ".trt", ".plan"):
            with self.subTest(ext=ext):
                self.assertEqual(_detect_format(f"model{ext}"), "tensorrt")

    def test_unknown_extension(self) -> None:
        self.assertEqual(_detect_format("model.pt"), "unknown")
        self.assertEqual(_detect_format("model.pb"), "unknown")

    def test_no_extension(self) -> None:
        self.assertEqual(_detect_format("mymodel"), "unknown")


# ---------------------------------------------------------------------------
# Tests -- quantization detection
# ---------------------------------------------------------------------------


class TestQuantizationDetection(unittest.TestCase):
    """Verify quantization keyword heuristics."""

    def test_int8_in_filename(self) -> None:
        self.assertEqual(_detect_quantization("model_int8.onnx"), "INT8")

    def test_fp16_in_filename(self) -> None:
        self.assertEqual(_detect_quantization("resnet_fp16.engine"), "FP16")

    def test_quant_in_metadata(self) -> None:
        meta: Dict[str, Any] = {"precision": "int8_quantized"}
        self.assertEqual(_detect_quantization("model.onnx", meta), "INT8")

    def test_no_quant_returns_none(self) -> None:
        self.assertIsNone(_detect_quantization("model.onnx"))

    def test_bf16_in_filename(self) -> None:
        self.assertEqual(_detect_quantization("model_bf16.onnx"), "BF16")


# ---------------------------------------------------------------------------
# Tests -- memory / params estimation
# ---------------------------------------------------------------------------


class TestEstimationHelpers(unittest.TestCase):
    """Verify _estimate_memory and _estimate_params_millions."""

    def test_onnx_memory_multiplier(self) -> None:
        size = 10_000_000
        self.assertEqual(_estimate_memory(size, "onnx"), int(size * 2.5))

    def test_trt_memory_multiplier(self) -> None:
        size = 10_000_000
        self.assertEqual(_estimate_memory(size, "tensorrt"), int(size * 1.5))

    def test_unknown_memory_multiplier(self) -> None:
        size = 10_000_000
        self.assertEqual(_estimate_memory(size, "unknown"), int(size * 2.0))

    def test_onnx_params_estimate(self) -> None:
        # 40 MB ONNX ~= 40_000_000 / 4_000_000 = 10.0 M params
        result = _estimate_params_millions(40_000_000, "onnx")
        self.assertAlmostEqual(result, 10.0)

    def test_trt_params_estimate(self) -> None:
        # 60 MB TRT ~= 60_000_000 / 3_000_000 = 20.0 M params
        result = _estimate_params_millions(60_000_000, "tensorrt")
        self.assertAlmostEqual(result, 20.0)


# ---------------------------------------------------------------------------
# Tests -- input shape comparison
# ---------------------------------------------------------------------------


class TestInputShapeCheck(unittest.TestCase):
    """Verify _check_input_shape logic."""

    def test_matching_shape_passes(self) -> None:
        info: Dict[str, Any] = {"shape": [1, 3, 224, 224]}
        result = ModelValidator._check_input_shape(info, (1, 3, 224, 224))
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_rank_mismatch_fails(self) -> None:
        info: Dict[str, Any] = {"shape": [1, 3, 224]}
        result = ModelValidator._check_input_shape(info, (1, 3, 224, 224))
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertIn("rank", result.message.lower())

    def test_dimension_mismatch_fails(self) -> None:
        info: Dict[str, Any] = {"shape": [1, 3, 128, 128]}
        result = ModelValidator._check_input_shape(info, (1, 3, 224, 224))
        self.assertEqual(result.status, CheckStatus.FAIL)
        self.assertIn("dim", result.message.lower())

    def test_dynamic_dim_passes(self) -> None:
        info: Dict[str, Any] = {"shape": ["batch_size", 3, 224, 224]}
        result = ModelValidator._check_input_shape(info, (1, 3, 224, 224))
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_none_dim_passes(self) -> None:
        info: Dict[str, Any] = {"shape": [None, 3, 224, 224]}
        result = ModelValidator._check_input_shape(info, (1, 3, 224, 224))
        self.assertEqual(result.status, CheckStatus.PASS)

    def test_missing_shape_warns(self) -> None:
        info: Dict[str, Any] = {}
        result = ModelValidator._check_input_shape(info, (1, 3, 224, 224))
        self.assertEqual(result.status, CheckStatus.WARN)


# ---------------------------------------------------------------------------
# Tests -- full pipeline (integration with temp files)
# ---------------------------------------------------------------------------


class TestFullValidationPipeline(unittest.TestCase):
    """Integration tests exercising ``ModelValidator.validate()`` end-to-end."""

    def test_missing_model_returns_fail_immediately(self) -> None:
        validator = ModelValidator()
        result = validator.validate("/no/such/model.onnx")
        self.assertEqual(result.overall_status, CheckStatus.FAIL)
        self.assertEqual(result.checks[0].name, "file_exists")

    def test_valid_onnx_mock_file(self) -> None:
        """A .onnx file that passes size/format checks (structure skipped if ORT absent)."""
        path = _make_temp_file(".onnx", b"\x00" * 500_000)
        try:
            validator = ModelValidator()
            result = validator.validate(path)
            self.assertIn(result.overall_status, (CheckStatus.PASS, CheckStatus.WARN))
            self.assertEqual(result.model_format, "onnx")
            self.assertGreater(result.file_size_bytes, 0)
            # Should have at least: file_exists, file_size, format_detection
            check_names = [c.name for c in result.checks]
            self.assertIn("file_exists", check_names)
            self.assertIn("file_size", check_names)
            self.assertIn("format_detection", check_names)
        finally:
            _cleanup(path)

    def test_valid_trt_mock_file(self) -> None:
        """A .engine file passes size/format checks."""
        path = _make_temp_file(".engine", b"\x00" * 1_000_000)
        try:
            validator = ModelValidator()
            result = validator.validate(path)
            self.assertEqual(result.model_format, "tensorrt")
            self.assertIn(result.overall_status, (CheckStatus.PASS, CheckStatus.WARN))
        finally:
            _cleanup(path)

    def test_too_small_onnx_fails(self) -> None:
        path = _make_temp_file(".onnx", b"\x00" * 10)
        try:
            validator = ModelValidator()
            result = validator.validate(path)
            self.assertEqual(result.overall_status, CheckStatus.FAIL)
            size_check = next(c for c in result.checks if c.name == "file_size")
            self.assertEqual(size_check.status, CheckStatus.FAIL)
        finally:
            _cleanup(path)

    def test_unknown_format_warns(self) -> None:
        path = _make_temp_file(".pt", b"\x00" * 500_000)
        try:
            validator = ModelValidator()
            result = validator.validate(path)
            fmt_check = next(c for c in result.checks if c.name == "format_detection")
            self.assertEqual(fmt_check.status, CheckStatus.WARN)
        finally:
            _cleanup(path)

    def test_quantization_detected_in_pipeline(self) -> None:
        path = _make_temp_file(".onnx", b"\x00" * 500_000)
        try:
            # Rename to include quant keyword
            quant_path = path.replace(".onnx", "_int8.onnx")
            os.rename(path, quant_path)
            path = quant_path  # track for cleanup

            validator = ModelValidator()
            result = validator.validate(path)
            self.assertEqual(result.quantization, "INT8")
            quant_check = next(c for c in result.checks if c.name == "quantization_detection")
            self.assertEqual(quant_check.status, CheckStatus.PASS)
        finally:
            _cleanup(path)

    def test_expected_input_shape_passed_to_result(self) -> None:
        path = _make_temp_file(".onnx", b"\x00" * 500_000)
        try:
            validator = ModelValidator()
            # When ORT is unavailable, input_info will be None so shape
            # check is skipped.  Still verify it doesn't crash.
            result = validator.validate(path, expected_input_shape=(1, 3, 224, 224))
            self.assertIsNotNone(result)
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# Tests -- estimate_inference_requirements
# ---------------------------------------------------------------------------


class TestEstimateInferenceRequirements(unittest.TestCase):
    """Verify estimate_inference_requirements with real temp files."""

    def test_returns_inference_requirements(self) -> None:
        path = _make_temp_file(".onnx", b"\x00" * 40_000_000)  # ~40 MB
        try:
            reqs = ModelValidator.estimate_inference_requirements(path)
            self.assertIsInstance(reqs, InferenceRequirements)
            self.assertGreater(reqs.estimated_memory_bytes, 0)
            self.assertGreater(reqs.estimated_params_millions, 0)
            self.assertIn(reqs.recommended_batch_size, (1, 4, 8))
        finally:
            _cleanup(path)

    def test_large_model_gets_batch_one(self) -> None:
        # 2.4 GB file => ~600 M params (>500) => batch=1
        path = _make_temp_file(".onnx", b"\x00" * 2_400_000_000)
        try:
            reqs = ModelValidator.estimate_inference_requirements(path)
            self.assertEqual(reqs.recommended_batch_size, 1)
        finally:
            _cleanup(path)

    def test_int8_quant_detected_in_requirements(self) -> None:
        path = _make_temp_file(".onnx", b"\x00" * 500_000)
        try:
            qpath = path.replace(".onnx", "_int8.onnx")
            os.rename(path, qpath)
            path = qpath
            reqs = ModelValidator.estimate_inference_requirements(path)
            self.assertEqual(reqs.recommended_dtype, "int8")
        finally:
            _cleanup(path)


# ---------------------------------------------------------------------------
# Tests -- report generation
# ---------------------------------------------------------------------------


class TestReportGeneration(unittest.TestCase):
    """Verify JSON and text report outputs."""

    def _make_result(self) -> ValidationResult:
        return ValidationResult(
            overall_status=CheckStatus.WARN,
            checks=[
                CheckResult("file_exists", CheckStatus.PASS, "OK"),
                CheckResult("file_size", CheckStatus.PASS, "OK"),
                CheckResult("onnx_structure", CheckStatus.WARN, "ORT missing"),
            ],
            model_path="/tmp/model.onnx",
            model_format="onnx",
            file_size_bytes=123456,
            quantization=None,
            input_info=None,
            output_info=None,
        )

    def test_json_report_is_valid_json(self) -> None:
        report = ModelValidator.generate_validation_report(
            self._make_result(),
            fmt="json",
        )
        parsed = json.loads(report)
        self.assertEqual(parsed["overall_status"], "warn")
        self.assertEqual(len(parsed["checks"]), 3)

    def test_json_report_contains_all_fields(self) -> None:
        report = ModelValidator.generate_validation_report(
            self._make_result(),
            fmt="json",
        )
        parsed = json.loads(report)
        for key in (
            "overall_status",
            "model_path",
            "model_format",
            "file_size_bytes",
            "quantization",
            "checks",
        ):
            self.assertIn(key, parsed)

    def test_text_report_contains_status(self) -> None:
        report = ModelValidator.generate_validation_report(
            self._make_result(),
            fmt="text",
        )
        self.assertIn("WARN", report)
        self.assertIn("MODEL VALIDATION REPORT", report)
        self.assertIn("[PASS]", report)
        self.assertIn("[WARN]", report)

    def test_invalid_format_raises(self) -> None:
        with self.assertRaises(ValueError):
            ModelValidator.generate_validation_report(
                self._make_result(),
                fmt="xml",
            )


# ---------------------------------------------------------------------------
# Tests -- ValidationResult aggregation
# ---------------------------------------------------------------------------


class TestValidationResultAggregation(unittest.TestCase):
    """Verify that overall_status reflects the worst check."""

    def _build(self, statuses: List[CheckStatus]) -> ValidationResult:
        checks = [CheckResult(f"check_{i}", s, s.value) for i, s in enumerate(statuses)]
        return ModelValidator._build_result(
            checks,
            "/tmp/m.onnx",
            "onnx",
            1000,
            None,
            None,
            None,
        )

    def test_all_pass_gives_pass(self) -> None:
        r = self._build([CheckStatus.PASS, CheckStatus.PASS])
        self.assertEqual(r.overall_status, CheckStatus.PASS)

    def test_one_fail_gives_fail(self) -> None:
        r = self._build([CheckStatus.PASS, CheckStatus.FAIL, CheckStatus.WARN])
        self.assertEqual(r.overall_status, CheckStatus.FAIL)

    def test_warn_without_fail_gives_warn(self) -> None:
        r = self._build([CheckStatus.PASS, CheckStatus.WARN])
        self.assertEqual(r.overall_status, CheckStatus.WARN)


# ---------------------------------------------------------------------------
# Tests -- CheckStatus enum
# ---------------------------------------------------------------------------


class TestCheckStatusEnum(unittest.TestCase):
    """Verify CheckStatus values."""

    def test_values(self) -> None:
        self.assertEqual(CheckStatus.PASS.value, "pass")
        self.assertEqual(CheckStatus.WARN.value, "warn")
        self.assertEqual(CheckStatus.FAIL.value, "fail")


if __name__ == "__main__":
    unittest.main()
