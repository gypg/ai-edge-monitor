"""GPU memory tracker — correlate CPU RSS with GPU memory changes.

Uses simple linear regression on a sliding window to detect trends in
both RSS and GPU memory.  Four correlation patterns map to alert levels:

    RSS↑ + GPU↑  →  CRITICAL  (dual-channel leak)
    RSS↑ + GPU→  →  WARNING   (CPU-only leak)
    RSS→ + GPU↑  →  WARNING   (GPU-only leak)
    RSS→ + GPU→  →  None      (no leak)

The slope thresholds are deliberately kept simple (positive slope above
a configurable minimum) so the detector works on embedded hardware where
GPU memory reporting may be noisy or delayed.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Optional

LOG = logging.getLogger("memory_diagnostics.gpu_tracker")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

_MIN_SAMPLES = 5


@dataclass(frozen=True)
class GpuLeakAlert:
    """Alert emitted when a memory leak pattern is detected."""

    pattern: str                # "dual_leak" | "cpu_only_leak" | "gpu_only_leak"
    cpu_leak_detected: bool
    gpu_leak_detected: bool
    cpu_slope: float            # MB per ms (×1000 = MB/sec)
    gpu_slope: float            # MB per ms
    severity: str               # "CRITICAL" | "WARNING"


# ---------------------------------------------------------------------------
# Linear regression helper (self-contained, no external deps)
# ---------------------------------------------------------------------------

def _linear_slope(values: list[float], timestamps: list[int]) -> float:
    """Return the slope of a least-squares line fitted to (*timestamps*, *values*).

    Timestamps are in milliseconds; the returned slope is value-units per
    millisecond.  Returns 0.0 when the denominator would be zero (all
    timestamps identical).
    """
    n = len(values)
    if n < 2:
        return 0.0

    sum_x = sum(timestamps)
    sum_y = sum(values)
    sum_xy = sum(x * y for x, y in zip(timestamps, values))
    sum_x2 = sum(x * x for x in timestamps)

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0.0
    return (n * sum_xy - sum_x * sum_y) / denom


def _r_squared(values: list[float], timestamps: list[int]) -> float:
    """Return R² for the linear fit.  0.0 on degenerate input."""
    n = len(values)
    if n < 2:
        return 0.0

    mean_y = sum(values) / n
    ss_tot = sum((y - mean_y) ** 2 for y in values)
    if ss_tot == 0:
        # Perfectly constant → trivially well-fit but no trend.
        return 0.0

    slope = _linear_slope(values, timestamps)
    intercept = mean_y - slope * (sum(timestamps) / n)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(timestamps, values))
    return 1.0 - ss_res / ss_tot


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class GpuMemoryTracker:
    """Correlate CPU RSS with GPU memory changes using a sliding window.

    Parameters
    ----------
    window_size:
        Maximum number of observations kept in the sliding window.
    r_squared_threshold:
        Minimum R² to consider a trend significant.
    slope_threshold_mb_per_ms:
        Minimum absolute slope (MB / ms) to count as "leaking".
    """

    def __init__(
        self,
        window_size: int = 60,
        r_squared_threshold: float = 0.8,
        slope_threshold_mb_per_ms: float = 0.0001,
    ) -> None:
        self._window_size = window_size
        self._r_squared_threshold = r_squared_threshold
        self._slope_threshold = slope_threshold_mb_per_ms

        self._rss_values: deque[float] = deque(maxlen=window_size)
        self._gpu_values: deque[float] = deque(maxlen=window_size)
        self._gpu_timestamps: deque[int] = deque(maxlen=window_size)
        self._cpu_timestamps: deque[int] = deque(maxlen=window_size)

    # ---- public API -------------------------------------------------------

    def observe(
        self,
        rss_mb: float,
        gpu_mem_mb: Optional[float],
        timestamp_ms: int,
    ) -> Optional[GpuLeakAlert]:
        """Record one observation and return an alert if a leak is detected.

        Returns ``None`` when there are fewer than *MIN_SAMPLES* data
        points or when no leak pattern is found.
        """
        # Always record RSS.
        self._rss_values.append(rss_mb)
        self._cpu_timestamps.append(timestamp_ms)

        # GPU data may be unavailable.
        if gpu_mem_mb is not None:
            self._gpu_values.append(gpu_mem_mb)
            self._gpu_timestamps.append(timestamp_ms)

        # Need enough data for a meaningful regression.
        if len(self._rss_values) < _MIN_SAMPLES:
            return None

        cpu_leak = self._detect_trend(
            list(self._rss_values), list(self._cpu_timestamps)
        )

        # If GPU data is missing or insufficient, fall back to CPU-only
        # analysis.
        if len(self._gpu_values) < _MIN_SAMPLES:
            if cpu_leak:
                return GpuLeakAlert(
                    pattern="cpu_only_leak",
                    cpu_leak_detected=True,
                    gpu_leak_detected=False,
                    cpu_slope=_linear_slope(
                        list(self._rss_values), list(self._cpu_timestamps)
                    ),
                    gpu_slope=0.0,
                    severity="WARNING",
                )
            return None

        gpu_leak = self._detect_trend(
            list(self._gpu_values), list(self._gpu_timestamps)
        )

        cpu_slope = _linear_slope(
            list(self._rss_values), list(self._cpu_timestamps)
        )
        gpu_slope = _linear_slope(
            list(self._gpu_values), list(self._gpu_timestamps)
        )

        if cpu_leak and gpu_leak:
            return GpuLeakAlert(
                pattern="dual_leak",
                cpu_leak_detected=True,
                gpu_leak_detected=True,
                cpu_slope=cpu_slope,
                gpu_slope=gpu_slope,
                severity="CRITICAL",
            )
        if cpu_leak:
            return GpuLeakAlert(
                pattern="cpu_only_leak",
                cpu_leak_detected=True,
                gpu_leak_detected=False,
                cpu_slope=cpu_slope,
                gpu_slope=gpu_slope,
                severity="WARNING",
            )
        if gpu_leak:
            return GpuLeakAlert(
                pattern="gpu_only_leak",
                cpu_leak_detected=False,
                gpu_leak_detected=True,
                cpu_slope=cpu_slope,
                gpu_slope=gpu_slope,
                severity="WARNING",
            )

        return None

    # ---- internals --------------------------------------------------------

    def _detect_trend(self, values: list[float], timestamps: list[int]) -> bool:
        """Return True if the series shows a significant positive slope."""
        r2 = _r_squared(values, timestamps)
        slope = _linear_slope(values, timestamps)
        return r2 >= self._r_squared_threshold and slope > self._slope_threshold
