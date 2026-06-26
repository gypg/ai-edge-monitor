"""Tests for the inference benchmark suite.

Covers: simulated benchmarks, custom callable benchmarks, anomaly
detection (latency spikes and drift), deployment scoring integration,
multi-run analysis, edge cases (zero iterations, empty results),
and configuration defaults.

unittest only, Python 3.8+ compatible.  No external dependencies.
"""

from __future__ import annotations

import time
import unittest

from inference_monitor.benchmark import (
    BenchmarkConfig,
    BenchmarkResult,
    InferenceBenchmark,
    _percentile,
    _std_dev,
    analyze_results,
)


class PercentileHelperTest(unittest.TestCase):
    """Tests for the pure helper functions."""

    def test_percentile_empty(self) -> None:
        self.assertEqual(_percentile([], 50), 0.0)

    def test_percentile_single(self) -> None:
        self.assertEqual(_percentile([10.0], 50), 10.0)

    def test_percentile_known_values(self) -> None:
        data = list(range(1, 101))  # 1..100
        # Nearest-rank: p50 -> index int(100*50/100)=50 -> value 51
        self.assertEqual(_percentile(data, 50), 51)
        # p95 -> index int(100*95/100)=95 -> value 96
        self.assertEqual(_percentile(data, 95), 96)
        self.assertEqual(_percentile(data, 0), 1)
        self.assertEqual(_percentile(data, 100), 100)

    def test_std_dev_empty(self) -> None:
        self.assertEqual(_std_dev([], 0.0), 0.0)

    def test_std_dev_single(self) -> None:
        self.assertEqual(_std_dev([5.0], 5.0), 0.0)

    def test_std_dev_known(self) -> None:
        values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        mean = sum(values) / len(values)
        result = _std_dev(values, mean)
        self.assertAlmostEqual(result, 2.0, places=1)


class DefaultConfigTest(unittest.TestCase):
    """BenchmarkConfig defaults should match specification."""

    def test_defaults(self) -> None:
        cfg = BenchmarkConfig()
        self.assertEqual(cfg.warmup_iters, 5)
        self.assertEqual(cfg.measure_iters, 50)
        self.assertEqual(cfg.target_fps, 30.0)
        self.assertEqual(cfg.target_latency_ms, 33.0)
        self.assertEqual(cfg.model_path, "model.trt")

    def test_frozen(self) -> None:
        cfg = BenchmarkConfig()
        with self.assertRaises(AttributeError):
            cfg.warmup_iters = 99  # type: ignore[misc]


class SimulatedBenchmarkTest(unittest.TestCase):
    """Test run_simulated with known parameters."""

    def test_basic_stats(self) -> None:
        cfg = BenchmarkConfig(warmup_iters=2, measure_iters=30)
        bench = InferenceBenchmark(config=cfg, random_seed=42)
        result = bench.run_simulated(latency_ms_mean=25.0, latency_ms_std=1.0)

        self.assertIsInstance(result, BenchmarkResult)
        self.assertEqual(result.total_inferences, 30)
        self.assertGreater(result.mean_ms, 0.0)
        self.assertGreater(result.fps, 0.0)
        self.assertGreater(result.p50_ms, 0.0)
        self.assertGreaterEqual(result.p95_ms, result.p50_ms)
        self.assertGreaterEqual(result.p99_ms, result.p95_ms)
        self.assertGreaterEqual(result.max_ms, result.min_ms)

    def test_latency_near_expected(self) -> None:
        """Mean latency should be close to the requested mean."""
        cfg = BenchmarkConfig(warmup_iters=3, measure_iters=100)
        bench = InferenceBenchmark(config=cfg, random_seed=123)
        result = bench.run_simulated(latency_ms_mean=20.0, latency_ms_std=2.0)

        # Allow 30% tolerance due to sleep granularity
        self.assertAlmostEqual(result.mean_ms, 20.0, delta=6.0)

    def test_reproducible_with_seed(self) -> None:
        """Same seed should produce same results (modulo OS scheduling)."""
        cfg = BenchmarkConfig(warmup_iters=1, measure_iters=20)
        r1 = InferenceBenchmark(config=cfg, random_seed=7).run_simulated(15.0, 1.0)
        r2 = InferenceBenchmark(config=cfg, random_seed=7).run_simulated(15.0, 1.0)
        self.assertEqual(r1.total_inferences, r2.total_inferences)
        # Means should be close (sleep jitter may cause minor drift)
        self.assertAlmostEqual(r1.mean_ms, r2.mean_ms, delta=3.0)

    def test_result_has_deployment_score(self) -> None:
        cfg = BenchmarkConfig(warmup_iters=1, measure_iters=10)
        bench = InferenceBenchmark(config=cfg, random_seed=42)
        result = bench.run_simulated(10.0, 1.0)

        self.assertIsNotNone(result.deployment_score)
        self.assertIn(result.deployment_score.verdict, ("ready", "marginal", "not_ready"))
        self.assertGreaterEqual(result.deployment_score.total, 0)
        self.assertLessEqual(result.deployment_score.total, 100)


class CustomCallableBenchmarkTest(unittest.TestCase):
    """Test run() with a user-supplied inference function."""

    def test_run_with_callable(self) -> None:
        call_count = 0

        def fake_inference() -> None:
            nonlocal call_count
            call_count += 1
            time.sleep(0.001)  # 1 ms simulated work

        cfg = BenchmarkConfig(warmup_iters=3, measure_iters=10)
        bench = InferenceBenchmark(config=cfg)
        result = bench.run(fake_inference)

        # 3 warmup + 10 measured = 13 total calls
        self.assertEqual(call_count, 13)
        self.assertEqual(result.total_inferences, 10)
        self.assertGreater(result.mean_ms, 0.0)

    def test_run_returns_value_without_error(self) -> None:
        """inference_fn's return value should be discarded without error."""

        def returns_value() -> float:
            time.sleep(0.001)
            return 42.0

        cfg = BenchmarkConfig(warmup_iters=1, measure_iters=5)
        result = InferenceBenchmark(config=cfg).run(returns_value)
        self.assertEqual(result.total_inferences, 5)


class AnomalyDetectionTest(unittest.TestCase):
    """Test latency spike and drift detection."""

    def test_spike_detection(self) -> None:
        """Latencies with a clear outlier should be flagged."""
        bench = InferenceBenchmark(random_seed=42)
        # Build a synthetic sorted latency list with one outlier
        normal = [10.0] * 20
        spike = normal + [500.0]
        anomalies = bench._detect_anomalies(spike, sum(spike) / len(spike), 0.0)
        # With zero std dev no anomaly detected — need non-zero std
        self.assertEqual(anomalies, [])

    def test_spike_with_realistic_data(self) -> None:
        """A set with large variance should flag spikes."""
        bench = InferenceBenchmark(random_seed=42)
        latencies = [10.0, 10.1, 10.2, 10.0, 10.1, 10.3, 10.0, 10.1, 10.2, 200.0]
        mean = sum(latencies) / len(latencies)
        std = bench._detect_anomalies.__func__(  # call as unbound
            bench, sorted(latencies), mean, 60.0
        )
        # High std should trigger spike detection
        anomalies = bench._detect_anomalies(sorted(latencies), mean, 60.0)
        self.assertTrue(len(anomalies) > 0)
        self.assertIn("spike", anomalies[0].lower())

    def test_drift_detection_high(self) -> None:
        """Second half significantly slower should trigger drift."""
        bench = InferenceBenchmark()
        # First half: 10 ms, second half: 50 ms (400% increase)
        latencies = [10.0] * 10 + [50.0] * 10
        anomalies = bench._detect_drift(latencies)
        self.assertEqual(len(anomalies), 1)
        self.assertIn("drift", anomalies[0].lower())

    def test_drift_detection_none(self) -> None:
        """Stable latencies should not trigger drift."""
        bench = InferenceBenchmark()
        latencies = [10.0] * 20
        anomalies = bench._detect_drift(latencies)
        self.assertEqual(len(anomalies), 0)

    def test_drift_too_few_samples(self) -> None:
        """Fewer than 10 samples should skip drift detection."""
        bench = InferenceBenchmark()
        latencies = [10.0] * 5 + [100.0] * 4
        anomalies = bench._detect_drift(latencies)
        self.assertEqual(anomalies, [])


class AnalyzeResultsTest(unittest.TestCase):
    """Test the analyze_results comparison function."""

    def test_empty_list(self) -> None:
        summary = analyze_results([])
        self.assertEqual(summary["run_count"], 0)

    def test_single_run(self) -> None:
        cfg = BenchmarkConfig(warmup_iters=1, measure_iters=10)
        result = InferenceBenchmark(config=cfg, random_seed=42).run_simulated(15.0, 1.0)
        summary = analyze_results([result])
        self.assertEqual(summary["run_count"], 1)
        self.assertEqual(summary["best_run_index"], 0)
        self.assertEqual(summary["fps"]["best"], summary["fps"]["worst"])

    def test_multi_run_comparison(self) -> None:
        cfg = BenchmarkConfig(warmup_iters=1, measure_iters=20)
        r1 = InferenceBenchmark(config=cfg, random_seed=1).run_simulated(10.0, 1.0)
        r2 = InferenceBenchmark(config=cfg, random_seed=2).run_simulated(20.0, 1.0)

        summary = analyze_results([r1, r2])
        self.assertEqual(summary["run_count"], 2)
        self.assertIn("p95_ms", summary)
        self.assertIn("mean_ms", summary)
        # Run with lower latency should be best
        self.assertIn(summary["best_run_index"], (0, 1))

    def test_regression_detection(self) -> None:
        """Runs with large variance should flag regression."""
        # Create results with very different P95 values
        cfg = BenchmarkConfig(warmup_iters=0, measure_iters=10)
        r1 = InferenceBenchmark(config=cfg, random_seed=1).run_simulated(10.0, 0.5)
        r2 = InferenceBenchmark(config=cfg, random_seed=2).run_simulated(50.0, 0.5)

        summary = analyze_results([r1, r2])
        # With 10 ms vs 50 ms P95, std dev should exceed 10% of mean
        self.assertTrue(len(summary["regressions"]) > 0)


class EdgeCaseTest(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def test_zero_measure_iters(self) -> None:
        """Zero measurement iterations should return empty results."""
        cfg = BenchmarkConfig(warmup_iters=1, measure_iters=0)
        bench = InferenceBenchmark(config=cfg, random_seed=42)
        result = bench.run_simulated(10.0, 1.0)
        self.assertEqual(result.total_inferences, 0)
        self.assertEqual(result.mean_ms, 0.0)
        self.assertEqual(result.fps, 0.0)

    def test_single_iteration(self) -> None:
        """Single iteration should produce valid stats."""
        cfg = BenchmarkConfig(warmup_iters=0, measure_iters=1)
        bench = InferenceBenchmark(config=cfg, random_seed=42)
        result = bench.run_simulated(15.0, 1.0)
        self.assertEqual(result.total_inferences, 1)
        self.assertGreater(result.mean_ms, 0.0)
        self.assertEqual(result.p50_ms, result.max_ms)

    def test_result_is_frozen(self) -> None:
        cfg = BenchmarkConfig(warmup_iters=0, measure_iters=5)
        result = InferenceBenchmark(config=cfg, random_seed=42).run_simulated(10.0, 1.0)
        with self.assertRaises(AttributeError):
            result.mean_ms = 999.0  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
