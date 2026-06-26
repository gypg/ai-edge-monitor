"""Tests for the ML-based anomaly detection module.

Run with:  python tests/ai_advisor/test_anomaly_detector.py
"""

from __future__ import annotations

import math
import unittest
from typing import List

from ai_advisor.anomaly_detector import (
    AnomalyResult,
    EWMADetector,
    IQRDetector,
    MetricAnomalyDetector,
    MultivariateDetector,
    ZScoreDetector,
)

# ---------------------------------------------------------------------------
# Z-score tests
# ---------------------------------------------------------------------------


class TestZScoreDetectorNormal(unittest.TestCase):
    """Z-score should NOT flag values within the threshold."""

    def test_normal_values_not_flagged(self) -> None:
        det = ZScoreDetector(window_size=50, threshold=3.0)
        # Feed 50 values centred on 100 with small noise
        for i in range(50):
            det.update(100.0 + (i % 5) * 0.1)
        result = det.detect(100.5)
        self.assertIsNone(result)


class TestZScoreDetectorAnomaly(unittest.TestCase):
    """Z-score MUST flag a value far from the rolling mean."""

    def test_extreme_value_detected(self) -> None:
        det = ZScoreDetector(window_size=100, threshold=3.0)
        # Band around 50 with slight variation so std > 0
        for i in range(50):
            det.update(50.0 + (i % 3))  # values in {50, 51, 52}
        # Spike far outside
        result = det.detect(100.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.method, "zscore")  # type: ignore[union-attr]
        self.assertIn(result.severity, ("info", "warning", "critical"))  # type: ignore[union-attr]

    def test_severity_scales_with_distance(self) -> None:
        """Farther outliers should have higher severity."""
        det = ZScoreDetector(window_size=100, threshold=3.0)
        for i in range(50):
            det.update(50.0 + (i % 3))
        mild = det.detect(58.0)
        extreme = det.detect(200.0)
        self.assertIsNotNone(mild)
        self.assertIsNotNone(extreme)
        # The extreme outlier must be at least as severe
        severity_order = {"info": 0, "warning": 1, "critical": 2}
        self.assertGreaterEqual(
            severity_order[extreme.severity],  # type: ignore[index]
            severity_order[mild.severity],  # type: ignore[index]
        )


# ---------------------------------------------------------------------------
# IQR tests
# ---------------------------------------------------------------------------


class TestIQRDetectorSkewed(unittest.TestCase):
    """IQR should handle skewed distributions gracefully."""

    def test_right_skewed_outlier(self) -> None:
        det = IQRDetector(window_size=100)
        # Right-skewed distribution: most values near 10, with variation
        values: List[float] = [
            10.0,
            10.5,
            11.0,
            9.5,
            10.2,
            10.8,
            9.8,
            11.5,
            10.0,
            9.0,
            10.3,
            10.7,
            9.7,
            11.2,
            10.1,
            10.9,
            9.3,
            11.0,
            10.4,
            10.6,
        ]
        for v in values:
            det.update(v)
        # This extreme value should be an outlier
        result = det.detect(50.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.method, "iqr")  # type: ignore[union-attr]

    def test_normal_value_not_flagged(self) -> None:
        det = IQRDetector(window_size=100)
        for v in [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]:
            det.update(float(v))
        result = det.detect(15.0)
        self.assertIsNone(result)


class TestIQRDetectorExtreme(unittest.TestCase):
    """Values beyond 3 * IQR should be flagged as critical."""

    def test_extreme_outlier_is_critical(self) -> None:
        det = IQRDetector(window_size=100)
        # Narrow distribution with slight variation so IQR > 0
        for v in [
            100.0,
            100.2,
            100.5,
            99.8,
            100.1,
            99.9,
            100.3,
            99.7,
            100.4,
            101.0,
            99.0,
            100.5,
            99.5,
        ]:
            det.update(v)
        result = det.detect(500.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, "critical")  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# EWMA tests
# ---------------------------------------------------------------------------


class TestEWMADetectorDrift(unittest.TestCase):
    """EWMA should detect gradual drift that Z-score might miss."""

    def test_gradual_drift_detected(self) -> None:
        det = EWMADetector(alpha=0.3, threshold=3.0)
        # Slowly increasing temperature — all in-band so far
        for temp in range(50, 70):
            det.update(float(temp))
        # Sudden jump (drift acceleration)
        result = det.detect(90.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.method, "ewma")  # type: ignore[union-attr]

    def test_smooth_series_not_flagged(self) -> None:
        det = EWMADetector(alpha=0.3, threshold=3.0)
        for v in [20.0, 21.0, 20.5, 21.5, 20.0, 21.0, 20.5]:
            det.update(v)
        result = det.detect(21.0)
        self.assertIsNone(result)

    def test_invalid_alpha_raises(self) -> None:
        with self.assertRaises(ValueError):
            EWMADetector(alpha=0.0)
        with self.assertRaises(ValueError):
            EWMADetector(alpha=1.5)


# ---------------------------------------------------------------------------
# Multivariate tests
# ---------------------------------------------------------------------------


class TestMultivariateDetectorCorrelation(unittest.TestCase):
    """Detect when expected correlation between two metrics breaks."""

    def test_positive_correlation_violation(self) -> None:
        det = MultivariateDetector(
            pairs=[("temp_max_c", "gpu_percent", 1)],
            window_size=30,
            z_threshold=1.5,
        )
        # Both rise together (positive correlation)
        for t, g in zip(range(50, 70), range(30, 50)):
            det.update("temp_max_c", float(t))
            det.update("gpu_percent", float(g))
        # Now temp keeps rising but GPU drops — correlation violated
        det.update("temp_max_c", 85.0)
        det.update("gpu_percent", 10.0)
        results = det.detect()
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0].method, "multivariate")

    def test_no_violation_when_correlated(self) -> None:
        det = MultivariateDetector(
            pairs=[("temp_max_c", "gpu_percent", 1)],
            window_size=30,
            z_threshold=2.0,
        )
        for t, g in zip(range(50, 80), range(30, 60)):
            det.update("temp_max_c", float(t))
            det.update("gpu_percent", float(g))
        # Both still rising together
        det.update("temp_max_c", 81.0)
        det.update("gpu_percent", 61.0)
        results = det.detect()
        self.assertEqual(len(results), 0)


class TestMultivariateDetectorNegativeCorrelation(unittest.TestCase):
    """Detect negative correlation violations (e.g., latency vs FPS)."""

    def test_negative_correlation_violation(self) -> None:
        det = MultivariateDetector(
            pairs=[("latency_ms", "fps", -1)],
            window_size=30,
            z_threshold=1.5,
        )
        # Normally inverse: latency goes up, fps goes down
        data = [
            (10, 60),
            (12, 55),
            (15, 50),
            (18, 45),
            (20, 40),
            (22, 38),
            (25, 35),
            (28, 30),
            (30, 28),
            (32, 25),
        ]
        for lat, fps in data:
            det.update("latency_ms", float(lat))
            det.update("fps", float(fps))
        # Both suddenly spike in the same direction — violates negative corr
        det.update("latency_ms", 50.0)
        det.update("fps", 70.0)
        results = det.detect()
        self.assertGreater(len(results), 0)


# ---------------------------------------------------------------------------
# MetricAnomalyDetector (high-level) tests
# ---------------------------------------------------------------------------


class TestMetricAnomalyDetectorRegistration(unittest.TestCase):
    def test_register_and_update(self) -> None:
        mad = MetricAnomalyDetector()
        mad.add_metric("temp", method="zscore")
        mad.update("temp", 50.0)
        anomalies = mad.check_all()
        # Single value — no anomaly possible (need 2+ for z-score)
        self.assertEqual(len(anomalies), 0)

    def test_unknown_metric_raises(self) -> None:
        mad = MetricAnomalyDetector()
        with self.assertRaises(KeyError):
            mad.update("nonexistent", 42.0)

    def test_unknown_method_raises(self) -> None:
        mad = MetricAnomalyDetector()
        with self.assertRaises(ValueError):
            mad.add_metric("x", method="svm")


class TestMetricAnomalyDetectorHealthScore(unittest.TestCase):
    def test_perfect_score_when_all_normal(self) -> None:
        mad = MetricAnomalyDetector()
        mad.add_metric("temp", method="zscore")
        for v in [50.0, 51.0, 49.0, 50.5, 50.0, 49.5, 51.0, 50.0]:
            mad.update("temp", v)
        score = mad.get_health_score()
        self.assertAlmostEqual(score, 100.0, places=1)

    def test_score_drops_on_anomaly(self) -> None:
        mad = MetricAnomalyDetector()
        mad.add_metric("temp", method="zscore", threshold=2.0)
        # Stream with slight variation so std > 0
        for i in range(30):
            mad.update("temp", 50.0 + (i % 3))  # 50, 51, 52
        # Inject anomaly
        mad.update("temp", 999.0)
        score = mad.get_health_score()
        self.assertLess(score, 100.0)

    def test_score_floors_at_zero(self) -> None:
        mad = MetricAnomalyDetector()
        mad.add_metric("t1", method="zscore", threshold=1.0)
        mad.add_metric("t2", method="zscore", threshold=1.0)
        mad.add_metric("t3", method="zscore", threshold=1.0)
        mad.add_metric("t4", method="zscore", threshold=1.0)
        for i in range(20):
            mad.update("t1", 100.0 + (i % 2))
            mad.update("t2", 100.0 + (i % 2))
            mad.update("t3", 100.0 + (i % 2))
            mad.update("t4", 100.0 + (i % 2))
        # Extreme anomaly on every metric
        mad.update("t1", 1.0)
        mad.update("t2", 1.0)
        mad.update("t3", 1.0)
        mad.update("t4", 1.0)
        score = mad.get_health_score()
        self.assertGreaterEqual(score, 0.0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    def test_zscore_empty_window(self) -> None:
        det = ZScoreDetector()
        self.assertIsNone(det.detect(42.0))

    def test_zscore_single_value(self) -> None:
        det = ZScoreDetector()
        det.update(42.0)
        self.assertIsNone(det.detect(999.0))

    def test_zscore_constant_stream(self) -> None:
        det = ZScoreDetector()
        for _ in range(50):
            det.update(10.0)
        # std == 0, so no detection possible
        self.assertIsNone(det.detect(10.0))

    def test_iqr_too_few_values(self) -> None:
        det = IQRDetector()
        det.update(1.0)
        det.update(2.0)
        det.update(3.0)
        self.assertIsNone(det.detect(100.0))

    def test_ewma_warmup(self) -> None:
        det = EWMADetector()
        det.update(10.0)
        self.assertIsNone(det.detect(999.0))

    def test_multivariate_insufficient_data(self) -> None:
        det = MultivariateDetector(pairs=[("a", "b", 1)])
        det.update("a", 1.0)
        det.update("b", 2.0)
        self.assertEqual(det.detect(), [])


# ---------------------------------------------------------------------------
# Integration with DiagnosticEngine
# ---------------------------------------------------------------------------


class TestIntegrationWithDiagnosticEngine(unittest.TestCase):
    """Verify that anomaly results can feed into the existing engine."""

    def test_anomaly_results_as_diagnostic_input(self) -> None:
        from ai_advisor.engine import DiagnosticEngine

        mad = MetricAnomalyDetector()
        mad.add_metric("temp_max_c", method="zscore", threshold=2.0)
        for _ in range(30):
            mad.update("temp_max_c", 50.0)
        # Push temp high enough to also trigger the thermal_warning rule
        mad.update("temp_max_c", 75.0)
        anomalies = mad.check_all()

        # Feed the same snapshot into the diagnostic engine
        engine = DiagnosticEngine(cooldown_sec=0)
        summary = {"temp_max_c": 75.0}
        diagnoses = engine.diagnose(summary)

        # At least one of the two systems should fire
        fired_something = len(anomalies) > 0 or len(diagnoses) > 0
        self.assertTrue(fired_something, "Expected at least one detection system to fire")

    def test_health_score_informs_engine_priority(self) -> None:
        """When health score is low, critical anomalies should exist."""
        mad = MetricAnomalyDetector()
        mad.add_metric("temp_max_c", method="ewma", alpha=0.5, threshold=2.0)
        # Warm up with stable temps (need variation so EWMA variance > 0)
        for i in range(20):
            mad.update("temp_max_c", 50.0 + (i % 3))  # 50, 51, 52 repeating
        # Spike to critical
        mad.update("temp_max_c", 150.0)
        anomalies = mad.check_all()
        score = mad.get_health_score()

        self.assertLess(score, 100.0)
        self.assertTrue(
            any(a.severity in ("warning", "critical") for a in anomalies),
            "Expected at least one warning/critical anomaly when score drops",
        )


# ---------------------------------------------------------------------------
# AnomalyResult dataclass
# ---------------------------------------------------------------------------


class TestAnomalyResultDataclass(unittest.TestCase):
    def test_frozen(self) -> None:
        r = AnomalyResult(
            metric_name="t",
            value=1.0,
            expected_range=(0.0, 2.0),
            z_score=0.5,
            method="zscore",
            severity="info",
        )
        with self.assertRaises(AttributeError):
            r.severity = "critical"  # type: ignore[misc]

    def test_fields(self) -> None:
        r = AnomalyResult(
            metric_name="gpu",
            value=99.0,
            expected_range=(0.0, 90.0),
            z_score=4.5,
            method="iqr",
            severity="critical",
        )
        self.assertEqual(r.metric_name, "gpu")
        self.assertEqual(r.method, "iqr")
        self.assertEqual(r.severity, "critical")


if __name__ == "__main__":
    unittest.main()
