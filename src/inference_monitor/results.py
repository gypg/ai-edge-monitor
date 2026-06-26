"""Data structures for inference monitoring results.

Provides lightweight, immutable-style dataclasses that capture the full
output of an inference benchmarking session: latency percentiles, FPS,
GPU metrics, power/energy, temperature, and optional per-layer profiling.

Python 3.8+ compatible.  No external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class LayerProfile:
    """Per-layer profiling entry (TensorRT / ONNX Runtime).

    Attributes:
        name: Layer / operator name.
        avg_time_ms: Average wall-clock time in milliseconds.
        calls: Number of times this layer was invoked.
    """

    name: str
    avg_time_ms: float
    calls: int


@dataclass
class InferenceResults:
    """Aggregated results of an inference monitoring session.

    All latency fields are in **milliseconds**.  GPU-related fields are
    ``None`` when ``gpu_monitor=False`` or the platform lacks a GPU.
    ``layer_profile`` is ``None`` when the framework does not support
    per-layer profiling (or the required runtime is missing).
    """

    model_path: str
    framework: str
    total_inferences: int
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    fps: float
    gpu_util_avg: Optional[float] = None
    gpu_mem_peak_mb: Optional[float] = None
    power_avg_watt: Optional[float] = None
    energy_joule: Optional[float] = None
    temperature_peak_c: Optional[float] = None
    layer_profile: Optional[List[LayerProfile]] = field(default=None)


@dataclass
class DeploymentScore:
    """Deployment readiness score produced by :class:`DeploymentScorer`.

    ``total`` is the weighted composite (0-100).  ``verdict`` is one of
    ``"ready"`` (>= 80), ``"marginal"`` (>= 50), or ``"not_ready"`` (< 50).
    ``bottlenecks`` lists human-readable descriptions of the weakest
    sub-scores.
    """

    total: int
    fps_score: int
    latency_score: int
    thermal_score: int
    power_score: int
    verdict: str
    bottlenecks: List[str] = field(default_factory=list)
