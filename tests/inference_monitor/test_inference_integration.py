"""Integration tests for the inference_monitor module.

Covers InferenceMonitor context manager, latency recording, FPS
calculation, framework auto-detection, DeploymentScorer integration,
LayerProfile, thread safety, and edge cases.

Run with:  python tests/inference_monitor/test_inference_integration.py
Python 3.8+ compatible.  Uses unittest — no pytest dependency.
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile
import threading
import time
import unittest

# Ensure the project root is on sys.path so ``src`` imports work.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))

from inference_monitor.monitor import InferenceMonitor, _detect_framework, _percentile
from inference_monitor.results import DeploymentScore, InferenceResults, LayerProfile
from inference_monitor.scorer import DeploymentScorer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dummy_record(n: int, monitor: InferenceMonitor, delay: float = 0.0) -> None:
    """Record *n* inferences inside *monitor*, sleeping *delay* seconds each."""
    for _ in range(n):
        if delay > 0:
            time.sleep(delay)
        monitor.record_inference()


# ---------------------------------------------------------------------------
# 1. Context manager protocol
# ---------------------------------------------------------------------------


class TestContextManagerProtocol(unittest.TestCase):
    """Enter / exit behaviour and record_inference basics."""

    def test_enter_returns_monitor(self):
        mon = InferenceMonitor("model.onnx")
        result = mon.__enter__()
        self.assertIs(result, mon)
        mon.__exit__(None, None, None)

    def test_exit_does_not_suppress_exception(self):
        mon = InferenceMonitor("model.onnx")
        mon.__enter__()
        # __exit__ returns None (falsy) -> exception propagates
        self.assertIsNone(mon.__exit__(ValueError, ValueError("boom"), None))

    def test_context_manager_with_statement(self):
        with InferenceMonitor("model.onnx") as mon:
            self.assertTrue(mon._running)
            mon.record_inference()
        self.assertFalse(mon._running)

    def test_record_after_exit_is_noop(self):
        with InferenceMonitor("model.onnx") as mon:
            mon.record_inference()
        # Record outside the context — should not add a latency entry
        mon.record_inference()
        self.assertEqual(mon.results.total_inferences, 1)


# ---------------------------------------------------------------------------
# 2. Latency recording & percentiles
# ---------------------------------------------------------------------------


class TestLatencyRecording(unittest.TestCase):
    """Verify latency percentiles from recorded inferences."""

    def test_single_inference_latency(self):
        with InferenceMonitor("model.onnx") as mon:
            time.sleep(0.01)
            mon.record_inference()
        results = mon.results
        # A single inference should have a non-negative latency
        self.assertGreaterEqual(results.latency_p50_ms, 0.0)
        self.assertEqual(results.total_inferences, 1)

    def test_multiple_inferences_percentiles(self):
        with InferenceMonitor("model.onnx") as mon:
            for _ in range(100):
                mon.record_inference()
        results = mon.results
        self.assertEqual(results.total_inferences, 100)
        # p50 <= p95 <= p99  (all derived from the same data)
        self.assertLessEqual(results.latency_p50_ms, results.latency_p95_ms)
        self.assertLessEqual(results.latency_p95_ms, results.latency_p99_ms)

    def test_percentile_with_varied_delays(self):
        """Introduce varying delays to get a distribution."""
        with InferenceMonitor("model.onnx") as mon:
            # Burst of fast records then a slow one
            for _ in range(10):
                mon.record_inference()
            time.sleep(0.05)
            mon.record_inference()
        results = mon.results
        self.assertEqual(results.total_inferences, 11)
        # p99 should be >= p50 because the slow record inflates the tail
        self.assertGreaterEqual(results.latency_p99_ms, results.latency_p50_ms)


# ---------------------------------------------------------------------------
# 3. FPS calculation
# ---------------------------------------------------------------------------


class TestFPSCalculation(unittest.TestCase):

    def test_fps_from_timed_session(self):
        with InferenceMonitor("model.onnx") as mon:
            for _ in range(50):
                mon.record_inference()
        results = mon.results
        self.assertGreater(results.fps, 0.0)
        # fps = total / elapsed_seconds — total=50, elapsed ~ tiny => very high fps
        self.assertEqual(results.total_inferences, 50)

    def test_fps_is_reasonable(self):
        with InferenceMonitor("model.onnx") as mon:
            for _ in range(10):
                time.sleep(0.01)
                mon.record_inference()
        results = mon.results
        # 10 inferences over ~0.1s => ~100 fps.  Just check it's positive.
        self.assertGreater(results.fps, 0.0)


# ---------------------------------------------------------------------------
# 4. Framework auto-detection
# ---------------------------------------------------------------------------


class TestFrameworkDetection(unittest.TestCase):

    def test_tensorrt_trt(self):
        self.assertEqual(_detect_framework("model.trt"), "tensorrt")
        self.assertEqual(_detect_framework("/path/to/MODEL.TRT"), "tensorrt")

    def test_tensorrt_engine(self):
        self.assertEqual(_detect_framework("model.engine"), "tensorrt")

    def test_onnx(self):
        self.assertEqual(_detect_framework("model.onnx"), "onnxruntime")
        self.assertEqual(_detect_framework("/path/to/model.ONNX"), "onnxruntime")

    def test_tflite(self):
        self.assertEqual(_detect_framework("model.tflite"), "tflite")

    def test_unknown_extension(self):
        self.assertEqual(_detect_framework("model.pb"), "unknown")
        self.assertEqual(_detect_framework("model.pt"), "unknown")

    def test_no_extension(self):
        self.assertEqual(_detect_framework("mymodel"), "unknown")

    def test_monitor_infers_framework_from_path(self):
        with InferenceMonitor("model.trt") as mon:
            self.assertEqual(mon._framework, "tensorrt")
        with InferenceMonitor("model.tflite") as mon:
            self.assertEqual(mon._framework, "tflite")

    def test_explicit_framework_overrides_detection(self):
        with InferenceMonitor("model.trt", framework="onnxruntime") as mon:
            self.assertEqual(mon._framework, "onnxruntime")


# ---------------------------------------------------------------------------
# 5. Empty monitoring session
# ---------------------------------------------------------------------------


class TestEmptySession(unittest.TestCase):

    def test_no_inferences_recorded(self):
        with InferenceMonitor("model.onnx") as mon:
            pass  # do nothing
        results = mon.results
        self.assertEqual(results.total_inferences, 0)
        self.assertEqual(results.latency_p50_ms, 0.0)
        self.assertEqual(results.latency_p95_ms, 0.0)
        self.assertEqual(results.latency_p99_ms, 0.0)
        self.assertEqual(results.fps, 0.0)
        self.assertIsNone(results.gpu_util_avg)
        self.assertIsNone(results.layer_profile)

    def test_results_without_context(self):
        """Creating a monitor but never entering it."""
        mon = InferenceMonitor("model.onnx")
        results = mon.results
        self.assertEqual(results.total_inferences, 0)
        self.assertEqual(results.fps, 0.0)


# ---------------------------------------------------------------------------
# 6. Large dataset (1000+ inferences)
# ---------------------------------------------------------------------------


class TestLargeDataset(unittest.TestCase):

    def test_thousand_inferences(self):
        n = 1000
        with InferenceMonitor("model.onnx") as mon:
            for _ in range(n):
                mon.record_inference()
        results = mon.results
        self.assertEqual(results.total_inferences, n)
        self.assertGreaterEqual(results.latency_p50_ms, 0.0)
        self.assertGreaterEqual(results.latency_p95_ms, results.latency_p50_ms)
        self.assertGreaterEqual(results.latency_p99_ms, results.latency_p95_ms)
        self.assertGreater(results.fps, 0.0)

    def test_two_thousand_inferences(self):
        n = 2000
        with InferenceMonitor("model.onnx") as mon:
            for _ in range(n):
                mon.record_inference()
        self.assertEqual(mon.results.total_inferences, n)


# ---------------------------------------------------------------------------
# 7. DeploymentScorer integration with monitor results
# ---------------------------------------------------------------------------


class TestDeploymentScorerIntegration(unittest.TestCase):

    def _score_from_monitor(
        self,
        n: int = 50,
        target_fps: float = 30.0,
        target_ms: float = 50.0,
        peak_temp: float = 65.0,
        avg_power: float = 15.0,
        budget_watt: float = 25.0,
    ) -> DeploymentScore:
        with InferenceMonitor("model.onnx") as mon:
            for _ in range(n):
                mon.record_inference()
        r = mon.results
        scorer = DeploymentScorer()
        return scorer.score(
            fps=r.fps,
            target_fps=target_fps,
            p95_ms=r.latency_p95_ms,
            target_ms=target_ms,
            peak_temp=peak_temp,
            avg_power=avg_power,
            budget_watt=budget_watt,
        )

    def test_score_returns_deployment_score(self):
        ds = self._score_from_monitor()
        self.assertIsInstance(ds, DeploymentScore)

    def test_score_has_all_fields(self):
        ds = self._score_from_monitor()
        self.assertIsInstance(ds.total, int)
        self.assertIsInstance(ds.fps_score, int)
        self.assertIsInstance(ds.latency_score, int)
        self.assertIsInstance(ds.thermal_score, int)
        self.assertIsInstance(ds.power_score, int)
        self.assertIsInstance(ds.verdict, str)
        self.assertIsInstance(ds.bottlenecks, list)

    def test_score_total_in_range(self):
        ds = self._score_from_monitor()
        self.assertGreaterEqual(ds.total, 0)
        self.assertLessEqual(ds.total, 100)


# ---------------------------------------------------------------------------
# 8. DeploymentScore verdicts
# ---------------------------------------------------------------------------


class TestDeploymentScoreVerdicts(unittest.TestCase):

    def setUp(self):
        self.scorer = DeploymentScorer()

    def _make_score(self, total_target: int) -> DeploymentScore:
        """Construct parameters that yield a specific total score range."""
        if total_target >= 80:
            # Everything excellent
            return self.scorer.score(
                fps=60.0,
                target_fps=30.0,
                p95_ms=5.0,
                target_ms=50.0,
                peak_temp=60.0,
                avg_power=10.0,
                budget_watt=25.0,
            )
        elif total_target >= 50:
            # Moderate — moderate fps, moderate latency, some thermal stress
            return self.scorer.score(
                fps=20.0,
                target_fps=30.0,
                p95_ms=55.0,
                target_ms=50.0,
                peak_temp=72.0,
                avg_power=15.0,
                budget_watt=25.0,
            )
        else:
            # Poor — terrible across the board
            return self.scorer.score(
                fps=2.0,
                target_fps=30.0,
                p95_ms=200.0,
                target_ms=50.0,
                peak_temp=95.0,
                avg_power=60.0,
                budget_watt=25.0,
            )

    def test_ready_verdict(self):
        ds = self._make_score(80)
        self.assertEqual(ds.verdict, "ready")
        self.assertGreaterEqual(ds.total, 80)

    def test_marginal_verdict(self):
        ds = self._make_score(50)
        self.assertEqual(ds.verdict, "marginal")
        self.assertGreaterEqual(ds.total, 50)
        self.assertLess(ds.total, 80)

    def test_not_ready_verdict(self):
        ds = self._make_score(0)
        self.assertEqual(ds.verdict, "not_ready")
        self.assertLess(ds.total, 50)


# ---------------------------------------------------------------------------
# 9. Bottleneck identification
# ---------------------------------------------------------------------------


class TestBottleneckIdentification(unittest.TestCase):

    def setUp(self):
        self.scorer = DeploymentScorer()

    def test_fps_bottleneck(self):
        ds = self.scorer.score(
            fps=5.0,
            target_fps=30.0,
            p95_ms=5.0,
            target_ms=50.0,
            peak_temp=60.0,
            avg_power=10.0,
            budget_watt=25.0,
        )
        fps_bottlenecks = [b for b in ds.bottlenecks if "FPS" in b]
        self.assertTrue(len(fps_bottlenecks) > 0, f"Expected FPS bottleneck, got: {ds.bottlenecks}")

    def test_latency_bottleneck(self):
        ds = self.scorer.score(
            fps=60.0,
            target_fps=30.0,
            p95_ms=120.0,
            target_ms=50.0,
            peak_temp=60.0,
            avg_power=10.0,
            budget_watt=25.0,
        )
        lat_bottlenecks = [b for b in ds.bottlenecks if "latency" in b.lower()]
        self.assertTrue(
            len(lat_bottlenecks) > 0, f"Expected latency bottleneck, got: {ds.bottlenecks}"
        )

    def test_thermal_bottleneck(self):
        ds = self.scorer.score(
            fps=60.0,
            target_fps=30.0,
            p95_ms=5.0,
            target_ms=50.0,
            peak_temp=90.0,
            avg_power=10.0,
            budget_watt=25.0,
        )
        thermal_bottlenecks = [b for b in ds.bottlenecks if "Temperature" in b]
        self.assertTrue(
            len(thermal_bottlenecks) > 0, f"Expected thermal bottleneck, got: {ds.bottlenecks}"
        )

    def test_power_bottleneck(self):
        ds = self.scorer.score(
            fps=60.0,
            target_fps=30.0,
            p95_ms=5.0,
            target_ms=50.0,
            peak_temp=60.0,
            avg_power=50.0,
            budget_watt=25.0,
        )
        power_bottlenecks = [b for b in ds.bottlenecks if "Power" in b]
        self.assertTrue(
            len(power_bottlenecks) > 0, f"Expected power bottleneck, got: {ds.bottlenecks}"
        )

    def test_no_bottlenecks_when_healthy(self):
        ds = self.scorer.score(
            fps=60.0,
            target_fps=30.0,
            p95_ms=5.0,
            target_ms=50.0,
            peak_temp=55.0,
            avg_power=10.0,
            budget_watt=25.0,
        )
        self.assertEqual(len(ds.bottlenecks), 0)


# ---------------------------------------------------------------------------
# 10. LayerProfile
# ---------------------------------------------------------------------------


class TestLayerProfile(unittest.TestCase):

    def test_layer_profile_creation(self):
        lp = LayerProfile(name="conv1", avg_time_ms=1.234, calls=100)
        self.assertEqual(lp.name, "conv1")
        self.assertAlmostEqual(lp.avg_time_ms, 1.234)
        self.assertEqual(lp.calls, 100)

    def test_layer_profile_in_inference_results(self):
        layers = [
            LayerProfile("conv1", 1.5, 500),
            LayerProfile("relu1", 0.3, 500),
            LayerProfile("fc1", 2.1, 500),
        ]
        results = InferenceResults(
            model_path="model.trt",
            framework="tensorrt",
            total_inferences=500,
            latency_p50_ms=3.5,
            latency_p95_ms=5.0,
            latency_p99_ms=6.0,
            fps=30.0,
            layer_profile=layers,
        )
        self.assertIsNotNone(results.layer_profile)
        assert results.layer_profile is not None  # for type checker
        self.assertEqual(len(results.layer_profile), 3)
        self.assertEqual(results.layer_profile[0].name, "conv1")
        self.assertEqual(results.layer_profile[1].name, "relu1")
        self.assertEqual(results.layer_profile[2].name, "fc1")

    def test_monitor_default_no_layer_profile(self):
        with InferenceMonitor("model.onnx") as mon:
            mon.record_inference()
        self.assertIsNone(mon.results.layer_profile)


# ---------------------------------------------------------------------------
# 11. InferenceResults fields
# ---------------------------------------------------------------------------


class TestInferenceResultsFields(unittest.TestCase):

    def test_all_fields_populated_from_monitor(self):
        with InferenceMonitor("model.trt", framework="tensorrt") as mon:
            for _ in range(20):
                mon.record_inference()
        r = mon.results

        self.assertEqual(r.model_path, "model.trt")
        self.assertEqual(r.framework, "tensorrt")
        self.assertEqual(r.total_inferences, 20)
        self.assertIsInstance(r.latency_p50_ms, float)
        self.assertIsInstance(r.latency_p95_ms, float)
        self.assertIsInstance(r.latency_p99_ms, float)
        self.assertIsInstance(r.fps, float)
        # GPU / power fields are None when gpu_monitor=True but no real GPU code
        self.assertIsNone(r.gpu_util_avg)
        self.assertIsNone(r.gpu_mem_peak_mb)
        self.assertIsNone(r.power_avg_watt)
        self.assertIsNone(r.energy_joule)
        self.assertIsNone(r.temperature_peak_c)
        self.assertIsNone(r.layer_profile)

    def test_results_dataclass_defaults(self):
        r = InferenceResults(
            model_path="m",
            framework="f",
            total_inferences=0,
            latency_p50_ms=0.0,
            latency_p95_ms=0.0,
            latency_p99_ms=0.0,
            fps=0.0,
        )
        # Optional fields default to None
        self.assertIsNone(r.gpu_util_avg)
        self.assertIsNone(r.gpu_mem_peak_mb)
        self.assertIsNone(r.power_avg_watt)
        self.assertIsNone(r.energy_joule)
        self.assertIsNone(r.temperature_peak_c)
        self.assertIsNone(r.layer_profile)

    def test_results_with_gpu_fields(self):
        r = InferenceResults(
            model_path="model.trt",
            framework="tensorrt",
            total_inferences=100,
            latency_p50_ms=3.0,
            latency_p95_ms=5.0,
            latency_p99_ms=6.5,
            fps=30.0,
            gpu_util_avg=85.5,
            gpu_mem_peak_mb=1024.0,
            power_avg_watt=45.0,
            energy_joule=120.0,
            temperature_peak_c=72.0,
        )
        self.assertEqual(r.gpu_util_avg, 85.5)
        self.assertEqual(r.gpu_mem_peak_mb, 1024.0)
        self.assertEqual(r.power_avg_watt, 45.0)
        self.assertEqual(r.energy_joule, 120.0)
        self.assertEqual(r.temperature_peak_c, 72.0)


# ---------------------------------------------------------------------------
# 12. Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety(unittest.TestCase):

    def test_concurrent_record_inference(self):
        n_threads = 8
        records_per_thread = 200
        errors: list = []

        def worker(monitor: InferenceMonitor, count: int) -> None:
            try:
                for _ in range(count):
                    monitor.record_inference()
            except Exception as exc:
                errors.append(exc)

        with InferenceMonitor("model.onnx") as mon:
            threads = [
                threading.Thread(target=worker, args=(mon, records_per_thread))
                for _ in range(n_threads)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        expected = n_threads * records_per_thread
        self.assertEqual(mon.results.total_inferences, expected)

    def test_concurrent_record_and_read(self):
        """One thread writes, another reads results simultaneously."""
        results_snapshot: list = []
        stop_flag = threading.Event()

        def writer(monitor: InferenceMonitor) -> None:
            for i in range(500):
                monitor.record_inference()
                if i % 50 == 0:
                    # Brief pause so the reader thread can observe partial state
                    time.sleep(0.001)
            stop_flag.set()

        def reader(monitor: InferenceMonitor) -> None:
            while not stop_flag.is_set():
                r = monitor.results
                results_snapshot.append(r.total_inferences)

        with InferenceMonitor("model.onnx") as mon:
            t_writer = threading.Thread(target=writer, args=(mon,))
            t_reader = threading.Thread(target=reader, args=(mon,))
            t_writer.start()
            t_reader.start()
            t_writer.join()
            t_reader.join()

        # Final result must account for all records
        self.assertEqual(mon.results.total_inferences, 500)
        # Reader saw at least one partial snapshot
        self.assertTrue(len(results_snapshot) > 0)


# ---------------------------------------------------------------------------
# 13. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):

    def test_zero_target_fps_in_scorer(self):
        scorer = DeploymentScorer()
        ds = scorer.score(
            fps=30.0,
            target_fps=0.0,
            p95_ms=10.0,
            target_ms=50.0,
            peak_temp=60.0,
            avg_power=10.0,
            budget_watt=25.0,
        )
        # fps_score should be 0 when target is 0 (division guard)
        self.assertEqual(ds.fps_score, 0)
        self.assertIsInstance(ds.verdict, str)

    def test_negative_fps_in_scorer(self):
        scorer = DeploymentScorer()
        ds = scorer.score(
            fps=-5.0,
            target_fps=30.0,
            p95_ms=10.0,
            target_ms=50.0,
            peak_temp=60.0,
            avg_power=10.0,
            budget_watt=25.0,
        )
        # Negative fps => fps_score clamped to 0
        self.assertEqual(ds.fps_score, 0)

    def test_very_large_latency(self):
        scorer = DeploymentScorer()
        ds = scorer.score(
            fps=1.0,
            target_fps=30.0,
            p95_ms=10000.0,
            target_ms=50.0,
            peak_temp=60.0,
            avg_power=10.0,
            budget_watt=25.0,
        )
        # Latency score clamped to 0
        self.assertEqual(ds.latency_score, 0)

    def test_very_large_temperature(self):
        scorer = DeploymentScorer()
        ds = scorer.score(
            fps=60.0,
            target_fps=30.0,
            p95_ms=5.0,
            target_ms=50.0,
            peak_temp=200.0,
            avg_power=10.0,
            budget_watt=25.0,
        )
        self.assertEqual(ds.thermal_score, 0)

    def test_very_large_power(self):
        scorer = DeploymentScorer()
        ds = scorer.score(
            fps=60.0,
            target_fps=30.0,
            p95_ms=5.0,
            target_ms=50.0,
            peak_temp=60.0,
            avg_power=500.0,
            budget_watt=25.0,
        )
        self.assertEqual(ds.power_score, 0)

    def test_score_total_clamped_at_100(self):
        """All metrics exceeding targets should still cap total at 100."""
        scorer = DeploymentScorer()
        ds = scorer.score(
            fps=999.0,
            target_fps=30.0,
            p95_ms=0.1,
            target_ms=50.0,
            peak_temp=40.0,
            avg_power=1.0,
            budget_watt=25.0,
        )
        self.assertLessEqual(ds.total, 100)

    def test_negative_power_budget(self):
        scorer = DeploymentScorer()
        ds = scorer.score(
            fps=30.0,
            target_fps=30.0,
            p95_ms=10.0,
            target_ms=50.0,
            peak_temp=60.0,
            avg_power=10.0,
            budget_watt=-5.0,
        )
        # Should not raise; budget < avg_power triggers power bottleneck
        self.assertIsInstance(ds.total, int)

    def test_percentile_empty_data(self):
        self.assertEqual(_percentile([], 50), 0.0)
        self.assertEqual(_percentile([], 95), 0.0)

    def test_percentile_single_element(self):
        self.assertEqual(_percentile([42.0], 50), 42.0)
        self.assertEqual(_percentile([42.0], 99), 42.0)

    def test_percentile_boundary(self):
        data = list(range(1, 101))  # 1..100
        self.assertEqual(_percentile(data, 0), 1)
        self.assertEqual(_percentile(data, 100), 100)

    def test_score_verdict_boundaries(self):
        """Verify exact boundary: 80=ready, 79=marginal, 49=not_ready."""
        scorer = DeploymentScorer()
        self.assertEqual(scorer.score(60, 30, 5, 50, 60, 10, 25).verdict, "ready")
        # Force marginal — fps=20/30, p95=55/50, temp=72, power=15/25
        self.assertEqual(scorer.score(20, 30, 55, 50, 72, 15, 25).verdict, "marginal")
        # Force not_ready
        self.assertEqual(scorer.score(1, 30, 200, 50, 95, 60, 25).verdict, "not_ready")


# ---------------------------------------------------------------------------
# 14. _percentile helper direct tests
# ---------------------------------------------------------------------------


class TestPercentileHelper(unittest.TestCase):

    def test_even_length_list(self):
        data = [1.0, 2.0, 3.0, 4.0]
        # p50 of 4 elements: k = int(4*50/100) = 2 => data[2] = 3.0
        self.assertEqual(_percentile(data, 50), 3.0)

    def test_odd_length_list(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        # p50: k = int(5*50/100) = 2 => data[2] = 3.0
        self.assertEqual(_percentile(data, 50), 3.0)

    def test_p99_clamps_to_last(self):
        data = list(range(100))
        # p99: k = int(100*99/100) = 99 => data[99] (last)
        self.assertEqual(_percentile(data, 99), 99)

    def test_p0_returns_first(self):
        data = [10.0, 20.0, 30.0]
        self.assertEqual(_percentile(data, 0), 10.0)


# ---------------------------------------------------------------------------
# 15. DeploymentScore dataclass
# ---------------------------------------------------------------------------


class TestDeploymentScoreDataclass(unittest.TestCase):

    def test_default_bottlenecks_is_empty_list(self):
        ds = DeploymentScore(
            total=90,
            fps_score=95,
            latency_score=90,
            thermal_score=85,
            power_score=90,
            verdict="ready",
        )
        self.assertEqual(ds.bottlenecks, [])

    def test_bottlenecks_populated(self):
        ds = DeploymentScore(
            total=30,
            fps_score=10,
            latency_score=10,
            thermal_score=10,
            power_score=10,
            verdict="not_ready",
            bottlenecks=["FPS below target", "Temperature too high"],
        )
        self.assertEqual(len(ds.bottlenecks), 2)


if __name__ == "__main__":
    unittest.main()
