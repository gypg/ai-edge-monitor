"""InferenceMonitor — context manager wrapping inference calls.

Provides automatic timestamping of each inference, latency percentile
computation, FPS calculation, and optional GPU/power metric correlation.
Designed to work without any ML framework installed (graceful degrade).

Usage::

    with InferenceMonitor("model.trt") as mon:
        for frame in stream:
            engine.infer(frame)
            mon.record_inference()

    results = mon.results

Python 3.8+ compatible.  No external dependencies beyond stdlib and
existing project modules.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, List, Optional

from .results import InferenceResults, LayerProfile

LOG = logging.getLogger("inference_monitor")

# ---------------------------------------------------------------------------
# Framework auto-detection from file extension
# ---------------------------------------------------------------------------
_EXT_TO_FRAMEWORK = {
    ".trt": "tensorrt",
    ".engine": "tensorrt",
    ".onnx": "onnxruntime",
    ".tflite": "tflite",
}


def _detect_framework(model_path: str) -> str:
    """Return a framework name inferred from *model_path*'s extension."""
    _, ext = os.path.splitext(model_path.lower())
    return _EXT_TO_FRAMEWORK.get(ext, "unknown")


def _percentile(sorted_data: List[float], pct: float) -> float:
    """Return the *pct*-th percentile from *sorted_data*.

    Uses nearest-rank method.  *sorted_data* must be pre-sorted ascending.
    Returns 0.0 for empty input.
    """
    if not sorted_data:
        return 0.0
    k = max(0, min(len(sorted_data) - 1, int(len(sorted_data) * pct / 100.0)))
    return sorted_data[k]


class InferenceMonitor:
    """Context manager that timestamps each inference and computes results.

    Args:
        model_path: Path to the model file.  The extension is used for
            framework auto-detection when *framework* is ``"auto"``.
        framework: One of ``"auto"``, ``"tensorrt"``, ``"onnxruntime"``,
            ``"tflite"``.  Defaults to ``"auto"``.
        power_source: Optional name of a power source to correlate.
            Currently reserved for future integration with
            :mod:`power_monitor`.
        gpu_monitor: Whether to attempt GPU metric collection.  When
            ``False``, GPU-related result fields will be ``None``.
    """

    def __init__(
        self,
        model_path: str,
        framework: str = "auto",
        power_source: Optional[str] = None,
        gpu_monitor: bool = True,
    ) -> None:
        self._model_path = model_path
        self._framework = (
            framework if framework != "auto" else _detect_framework(model_path)
        )
        self._power_source = power_source
        self._gpu_monitor = gpu_monitor

        # Timing state
        self._latencies: List[float] = []
        self._start_time: float = 0.0
        self._last_record_time: float = 0.0
        self._running: bool = False

    # -- context manager protocol -------------------------------------------

    def __enter__(self) -> "InferenceMonitor":
        self._latencies = []
        self._start_time = time.perf_counter()
        self._last_record_time = self._start_time
        self._running = True
        LOG.debug(
            "InferenceMonitor started for %s (framework=%s)",
            self._model_path,
            self._framework,
        )
        return self

    def __exit__(self, *exc: Any) -> None:
        self._running = False
        LOG.debug(
            "InferenceMonitor stopped for %s — %d inferences recorded",
            self._model_path,
            len(self._latencies),
        )
        # Never suppress exceptions
        return None

    # -- public API ---------------------------------------------------------

    def record_inference(self) -> None:
        """Record the completion of one inference call.

        Should be called **after** each inference finishes.  The elapsed
        time since the previous call (or ``__enter__``) is stored as the
        latency for this inference.
        """
        now = time.perf_counter()
        if self._running and self._last_record_time > 0:
            delta_ms = (now - self._last_record_time) * 1000.0
            self._latencies.append(delta_ms)
        self._last_record_time = now

    @property
    def results(self) -> InferenceResults:
        """Compute and return aggregated results.

        Can be called after the ``with`` block exits (or while it is
        still running, though the snapshot will be partial).
        """
        total = len(self._latencies)
        if total == 0:
            elapsed_sec = 0.0
            if self._start_time > 0:
                elapsed_sec = time.perf_counter() - self._start_time
            return InferenceResults(
                model_path=self._model_path,
                framework=self._framework,
                total_inferences=0,
                latency_p50_ms=0.0,
                latency_p95_ms=0.0,
                latency_p99_ms=0.0,
                fps=0.0,
                gpu_util_avg=None,
                gpu_mem_peak_mb=None,
                power_avg_watt=None,
                energy_joule=None,
                temperature_peak_c=None,
                layer_profile=None,
            )

        sorted_lat = sorted(self._latencies)
        elapsed_sec = time.perf_counter() - self._start_time if self._start_time > 0 else 0.0
        fps = total / elapsed_sec if elapsed_sec > 0 else 0.0

        return InferenceResults(
            model_path=self._model_path,
            framework=self._framework,
            total_inferences=total,
            latency_p50_ms=round(_percentile(sorted_lat, 50), 3),
            latency_p95_ms=round(_percentile(sorted_lat, 95), 3),
            latency_p99_ms=round(_percentile(sorted_lat, 99), 3),
            fps=round(fps, 2),
            gpu_util_avg=None,  # populated by GPU-aware subclass
            gpu_mem_peak_mb=None,
            power_avg_watt=None,
            energy_joule=None,
            temperature_peak_c=None,
            layer_profile=None,
        )
