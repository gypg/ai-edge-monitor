from __future__ import annotations

from collections import deque
from typing import List, Optional, Tuple

from .models import LeakAlert


def _linear_regression(
    xs: List[float], ys: List[float]
) -> Tuple[float, float, float]:
    """Pure-Python linear regression.

    Returns (slope, intercept, r_squared).
    """
    n = len(xs)
    if n < 2:
        return 0.0, 0.0, 0.0

    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xx = sum(x * x for x in xs)
    sum_xy = sum(x * y for x, y in zip(xs, ys))

    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return 0.0, 0.0, 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    y_mean = sum_y / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return slope, intercept, r_squared


class LeakDetector:
    """RSS-based memory leak detector using sliding-window linear regression."""

    def __init__(
        self,
        window_size: int = 60,
        r_squared_threshold: float = 0.8,
        slope_threshold_mb_per_sec: float = 0.1,
    ) -> None:
        self._window_size = window_size
        self._r_squared_threshold = r_squared_threshold
        self._slope_threshold = slope_threshold_mb_per_sec
        self._observations: deque = deque(maxlen=window_size)

    def observe(self, rss_mb: float, timestamp_ms: int) -> Optional[LeakAlert]:
        """Record a new RSS observation.

        Returns a LeakAlert when the sliding window shows a linear growth
        pattern that exceeds both the R-squared and slope thresholds.
        Returns None otherwise.
        """
        self._observations.append((timestamp_ms, rss_mb))

        if len(self._observations) < 2:
            return None

        # Convert to relative seconds for slope interpretation
        first_ts = self._observations[0][0]
        xs = [(ts - first_ts) / 1000.0 for ts, _ in self._observations]
        ys = [rss for _, rss in self._observations]

        slope, _intercept, r_squared = _linear_regression(xs, ys)

        if r_squared <= self._r_squared_threshold:
            return None
        if slope <= self._slope_threshold:
            return None

        # Estimate time to OOM assuming 2 GB limit (reasonable default)
        oom_limit_mb = 2048.0
        current_rss = ys[-1]
        if slope > 0 and current_rss < oom_limit_mb:
            estimated_tto = (oom_limit_mb - current_rss) / slope
        else:
            estimated_tto = None

        return LeakAlert(
            target_pid=0,
            target_name="",
            r_squared=r_squared,
            slope_mb_per_sec=slope,
            estimated_time_to_oom=estimated_tto,
            window_start_ms=self._observations[0][0],
            window_end_ms=self._observations[-1][0],
            sample_count=len(self._observations),
        )
