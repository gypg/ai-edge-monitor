"""ML-based anomaly detection for embedded device metrics.

Uses statistical methods (Z-score, IQR, EWMA) for real-time anomaly detection
without requiring heavy ML libraries (scikit-learn, etc.).

Detection methods:
1. Z-score — values beyond N standard deviations from rolling mean
2. IQR — values outside 1.5 * IQR from Q1/Q3
3. EWMA (Exponentially Weighted Moving Average) — detects gradual drift
4. Multivariate — correlated metric anomalies (e.g., high temp + low GPU)

Python 3.8+ compatible.  Zero external dependencies (pure stdlib math).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnomalyResult:
    """Single anomaly detection result."""

    metric_name: str
    value: float
    expected_range: Tuple[float, float]
    z_score: float
    method: str  # "zscore" | "iqr" | "ewma" | "multivariate"
    severity: str  # "info" | "warning" | "critical"


# ---------------------------------------------------------------------------
# Z-score detector
# ---------------------------------------------------------------------------


class ZScoreDetector:
    """Detects anomalies using Z-score against a rolling window.

    Parameters
    ----------
    window_size:
        Maximum number of recent values retained (default 100).
    threshold:
        Number of standard deviations beyond which a value is anomalous
        (default 3.0).
    """

    def __init__(self, window_size: int = 100, threshold: float = 3.0) -> None:
        self._window: deque = deque(maxlen=window_size)
        self._threshold = threshold

    def update(self, value: float) -> None:
        """Append *value* to the rolling window."""
        self._window.append(float(value))

    def detect(self, value: float) -> Optional[AnomalyResult]:
        """Check *value* against the current rolling statistics.

        Returns :class:`AnomalyResult` if anomalous, ``None`` otherwise.
        Needs at least 2 data points in the window to make a judgment.
        """
        if len(self._window) < 2:
            return None

        mean = sum(self._window) / len(self._window)
        variance = sum((x - mean) ** 2 for x in self._window) / len(self._window)
        std = math.sqrt(variance)

        if std == 0.0:
            return None  # constant stream — no deviation possible

        z = (value - mean) / std
        abs_z = abs(z)

        if abs_z < self._threshold:
            return None

        # Severity ramps with distance
        if abs_z >= self._threshold * 2:
            severity = "critical"
        elif abs_z >= self._threshold * 1.5:
            severity = "warning"
        else:
            severity = "info"

        return AnomalyResult(
            metric_name="",
            value=value,
            expected_range=(
                round(mean - self._threshold * std, 4),
                round(mean + self._threshold * std, 4),
            ),
            z_score=round(z, 4),
            method="zscore",
            severity=severity,
        )

    @property
    def window_size(self) -> int:
        """Current number of values in the rolling window."""
        return len(self._window)


# ---------------------------------------------------------------------------
# IQR detector
# ---------------------------------------------------------------------------


class IQRDetector:
    """Detects outliers using the Interquartile Range method.

    * 1.5 * IQR beyond Q1/Q3 → outlier (warning)
    * 3.0 * IQR beyond Q1/Q3 → extreme outlier (critical)

    Parameters
    ----------
    window_size:
        Maximum number of recent values retained (default 100).
    """

    def __init__(self, window_size: int = 100) -> None:
        self._window: deque = deque(maxlen=window_size)

    def update(self, value: float) -> None:
        """Append *value* to the rolling window."""
        self._window.append(float(value))

    @staticmethod
    def _percentile(sorted_data: List[float], p: float) -> float:
        """Compute the *p*-th percentile (0-1) of *sorted_data*."""
        n = len(sorted_data)
        if n == 0:
            return 0.0
        k = (n - 1) * p
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)

    def detect(self, value: float) -> Optional[AnomalyResult]:
        """Check *value* against the IQR boundaries.

        Returns :class:`AnomalyResult` if anomalous, ``None`` otherwise.
        Needs at least 4 data points for meaningful quartiles.
        """
        if len(self._window) < 4:
            return None

        s = sorted(self._window)
        q1 = self._percentile(s, 0.25)
        q3 = self._percentile(s, 0.75)
        iqr = q3 - q1

        if iqr == 0.0:
            return None

        lower_mild = q1 - 1.5 * iqr
        upper_mild = q3 + 1.5 * iqr
        lower_extreme = q1 - 3.0 * iqr
        upper_extreme = q3 + 3.0 * iqr

        if lower_extreme <= value <= upper_extreme:
            # Mild outliers still reported as info/warning
            if value < lower_mild or value > upper_mild:
                severity = "warning"
            else:
                return None
        else:
            severity = "critical"

        # Approximate z-score from IQR for uniform reporting
        median = self._percentile(s, 0.5)
        z = (value - median) / (iqr / 1.35) if iqr else 0.0

        return AnomalyResult(
            metric_name="",
            value=value,
            expected_range=(round(lower_mild, 4), round(upper_mild, 4)),
            z_score=round(z, 4),
            method="iqr",
            severity=severity,
        )

    @property
    def window_size(self) -> int:
        """Current number of values in the rolling window."""
        return len(self._window)


# ---------------------------------------------------------------------------
# EWMA detector
# ---------------------------------------------------------------------------


class EWMADetector:
    """Detects gradual drift using Exponentially Weighted Moving Average.

    Parameters
    ----------
    alpha:
        Smoothing factor in (0, 1].  Higher alpha = more responsive to recent
        changes (default 0.3).
    threshold:
        Number of rolling sigmas beyond which a value is flagged (default 3.0).
    """

    def __init__(self, alpha: float = 0.3, threshold: float = 3.0) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self._alpha = alpha
        self._threshold = threshold
        self._ewma: Optional[float] = None
        self._ewma_var: Optional[float] = None
        # Snapshot of EWMA *before* the latest update, used by detect()
        # so that the anomaly check compares the new value against the
        # prior smooth state (not the state that already absorbed it).
        self._prev_ewma: Optional[float] = None
        self._prev_ewma_var: Optional[float] = None
        self._count: int = 0

    def update(self, value: float) -> None:
        """Feed *value* into the EWMA state."""
        v = float(value)
        self._count += 1

        if self._ewma is None:
            self._ewma = v
            self._ewma_var = 0.0
        else:
            # Save previous state for detect()
            self._prev_ewma = self._ewma
            self._prev_ewma_var = self._ewma_var
            diff = v - self._ewma
            self._ewma = self._ewma + self._alpha * diff
            # Recursive variance estimate (Roberts 1959)
            assert self._ewma_var is not None
            self._ewma_var = (1 - self._alpha) * (self._ewma_var + self._alpha * diff * diff)

    def detect(self, value: float) -> Optional[AnomalyResult]:
        """Check *value* against EWMA +/- threshold * sigma.

        Uses the EWMA state *before* the latest ``update(value)`` call so that
        the check compares the new value against the prior smooth trend.

        Returns :class:`AnomalyResult` if anomalous, ``None`` otherwise.
        Needs at least 3 data points to warm up.
        """
        # Prefer the pre-update snapshot; fall back to current state
        ref_ewma = self._prev_ewma if self._prev_ewma is not None else self._ewma
        ref_var = self._prev_ewma_var if self._prev_ewma_var is not None else self._ewma_var

        if ref_ewma is None or ref_var is None or self._count < 3:
            return None

        std = math.sqrt(ref_var)
        if std == 0.0:
            return None

        z = (value - ref_ewma) / std
        abs_z = abs(z)

        if abs_z < self._threshold:
            return None

        if abs_z >= self._threshold * 2:
            severity = "critical"
        elif abs_z >= self._threshold * 1.5:
            severity = "warning"
        else:
            severity = "info"

        return AnomalyResult(
            metric_name="",
            value=value,
            expected_range=(
                round(ref_ewma - self._threshold * std, 4),
                round(ref_ewma + self._threshold * std, 4),
            ),
            z_score=round(z, 4),
            method="ewma",
            severity=severity,
        )

    @property
    def count(self) -> int:
        """Number of values processed so far."""
        return self._count


# ---------------------------------------------------------------------------
# Multivariate detector
# ---------------------------------------------------------------------------


class MultivariateDetector:
    """Detects correlated anomalies across multiple metric streams.

    Watches for contradictions such as temperature rising while GPU usage
    drops — a signature of thermal throttling.

    Parameters
    ----------
    pairs:
        List of ``(metric_a, metric_b, expected_sign)`` tuples.
        *expected_sign* is ``1`` for positive correlation and ``-1`` for
        negative correlation.
    window_size:
        Number of recent values kept per metric (default 50).
    z_threshold:
        Z-score threshold for individual metric anomalies (default 2.0).
    """

    def __init__(
        self,
        pairs: Optional[List[Tuple[str, str, int]]] = None,
        window_size: int = 50,
        z_threshold: float = 2.0,
    ) -> None:
        self._pairs = pairs or []
        self._window_size = window_size
        self._z_threshold = z_threshold
        self._streams: Dict[str, deque] = {}

    def update(self, metric_name: str, value: float) -> None:
        """Append *value* to the stream for *metric_name*."""
        if metric_name not in self._streams:
            self._streams[metric_name] = deque(maxlen=self._window_size)
        self._streams[metric_name].append(float(value))

    def detect(self) -> List[AnomalyResult]:
        """Evaluate all registered correlation pairs.

        Returns a list of anomalies where the expected correlation is violated.
        """
        results: List[AnomalyResult] = []

        for metric_a, metric_b, expected_sign in self._pairs:
            stream_a = self._streams.get(metric_a, deque())
            stream_b = self._streams.get(metric_b, deque())

            if len(stream_a) < 3 or len(stream_b) < 3:
                continue

            z_a = self._latest_z(stream_a)
            z_b = self._latest_z(stream_b)

            if z_a is None or z_b is None:
                continue

            # If both are extreme in the *same* direction when we expected
            # opposite, or vice versa, that's a correlated anomaly.
            product = z_a * z_b
            threshold_sq = self._z_threshold**2

            if expected_sign > 0 and product < -threshold_sq:
                severity = self._severity(abs(z_a), abs(z_b))
                results.append(
                    AnomalyResult(
                        metric_name=f"{metric_a}+{metric_b}",
                        value=stream_a[-1],
                        expected_range=(
                            round(stream_b[-1] - abs(z_b), 4),
                            round(stream_b[-1] + abs(z_b), 4),
                        ),
                        z_score=round(z_a, 4),
                        method="multivariate",
                        severity=severity,
                    )
                )
            elif expected_sign < 0 and product > threshold_sq:
                severity = self._severity(abs(z_a), abs(z_b))
                results.append(
                    AnomalyResult(
                        metric_name=f"{metric_a}+{metric_b}",
                        value=stream_a[-1],
                        expected_range=(
                            round(stream_b[-1] - abs(z_b), 4),
                            round(stream_b[-1] + abs(z_b), 4),
                        ),
                        z_score=round(z_a, 4),
                        method="multivariate",
                        severity=severity,
                    )
                )

        return results

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _latest_z(stream: deque) -> Optional[float]:
        """Compute the Z-score of the most recent value in *stream*."""
        if len(stream) < 2:
            return None
        mean = sum(stream) / len(stream)
        variance = sum((x - mean) ** 2 for x in stream) / len(stream)
        std = math.sqrt(variance)
        if std == 0.0:
            return None
        return (stream[-1] - mean) / std

    @staticmethod
    def _severity(abs_z_a: float, abs_z_b: float) -> str:
        avg = (abs_z_a + abs_z_b) / 2
        if avg >= 4.0:
            return "critical"
        if avg >= 3.0:
            return "warning"
        return "info"


# ---------------------------------------------------------------------------
# High-level aggregator
# ---------------------------------------------------------------------------

_SEVERITY_PENALTY = {"critical": 25, "warning": 10, "info": 3}


class MetricAnomalyDetector:
    """High-level interface that combines all detection methods.

    Usage::

        mad = MetricAnomalyDetector()
        mad.add_metric("temp_max_c", method="ewma")
        mad.add_metric("gpu_percent", method="zscore")
        for snapshot in monitor_stream:
            mad.update("temp_max_c", snapshot["temp_max_c"])
            mad.update("gpu_percent", snapshot["gpu_percent"])
            anomalies = mad.check_all()
            score = mad.get_health_score()
    """

    def __init__(self) -> None:
        self._detectors: Dict[str, Any] = {}  # name -> ZScoreDetector|IQRDetector|EWMADetector
        self._methods: Dict[str, str] = {}  # name -> method key
        self._multivariate: Optional[MultivariateDetector] = None
        self._latest_values: Dict[str, float] = {}

    def add_metric(
        self,
        name: str,
        method: str = "zscore",
        **kwargs: Any,
    ) -> None:
        """Register a metric with the chosen detection method.

        Parameters
        ----------
        name:
            Metric identifier (e.g. ``"temp_max_c"``).
        method:
            One of ``"zscore"``, ``"iqr"``, ``"ewma"``.
        **kwargs:
            Forwarded to the underlying detector constructor.
        """
        if method == "zscore":
            self._detectors[name] = ZScoreDetector(
                window_size=kwargs.get("window_size", 100),
                threshold=kwargs.get("threshold", 3.0),
            )
        elif method == "iqr":
            self._detectors[name] = IQRDetector(
                window_size=kwargs.get("window_size", 100),
            )
        elif method == "ewma":
            self._detectors[name] = EWMADetector(
                alpha=kwargs.get("alpha", 0.3),
                threshold=kwargs.get("threshold", 3.0),
            )
        else:
            raise ValueError(f"Unknown method: {method!r}")

        self._methods[name] = method

    def set_multivariate(
        self,
        pairs: List[Tuple[str, str, int]],
        **kwargs: Any,
    ) -> None:
        """Configure multivariate correlation detection.

        Parameters
        ----------
        pairs:
            List of ``(metric_a, metric_b, expected_sign)`` tuples.
        """
        self._multivariate = MultivariateDetector(
            pairs=pairs,
            window_size=kwargs.get("window_size", 50),
            z_threshold=kwargs.get("z_threshold", 2.0),
        )

    def update(self, name: str, value: float) -> None:
        """Feed a new data point for the registered metric *name*."""
        if name not in self._detectors:
            raise KeyError(f"Metric {name!r} not registered. Call add_metric() first.")
        self._detectors[name].update(value)
        self._latest_values[name] = float(value)
        if self._multivariate is not None:
            self._multivariate.update(name, value)

    def check_all(self) -> List[AnomalyResult]:
        """Check all registered metrics against their latest value.

        Returns a list of :class:`AnomalyResult` for every anomaly detected.
        """
        results: List[AnomalyResult] = []

        for name, detector in self._detectors.items():
            value = self._latest_values.get(name)
            if value is None:
                continue
            result = detector.detect(value)
            if result is not None:
                # Annotate with metric name (detectors leave it blank)
                results.append(
                    AnomalyResult(
                        metric_name=name,
                        value=result.value,
                        expected_range=result.expected_range,
                        z_score=result.z_score,
                        method=result.method,
                        severity=result.severity,
                    )
                )

        # Multivariate anomalies
        if self._multivariate is not None:
            results.extend(self._multivariate.detect())

        return results

    def get_health_score(self) -> float:
        """Return a health score in [0, 100].  100 = all normal.

        Each anomaly deducts points based on severity:
        - critical: -25
        - warning:  -10
        - info:     -3
        """
        anomalies = self.check_all()
        penalty = sum(_SEVERITY_PENALTY.get(a.severity, 0) for a in anomalies)
        return max(0.0, 100.0 - penalty)
