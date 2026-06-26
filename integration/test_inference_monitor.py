"""Integration: InferenceMonitor with dummy probe, aggregator, and scorer.

Tests:
    test_inference_monitor_dummy_mode
        - Run InferenceMonitor in dummy/force_dummy mode, verify results populated.
    test_inference_monitor_with_aggregator
        - Feed inference scenario data into AggregatorAnalyzer, verify summary.
    test_scorer_with_real_summary
        - Use AggregatorAnalyzer.get_summary_dict() as scorer input.

All tests use dummy/force_dummy mode.  Python 3.8+ compatible.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aggregator_analyzer import AggregatorAnalyzer  # noqa: E402
from inference_monitor.results import InferenceResults  # noqa: E402
from inference_monitor.scorer import DeploymentScorer  # noqa: E402
from platform_adapter.probe import DummyProbe, RawMetrics  # noqa: E402
from scenarios import InferenceScenario, make_scenario  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_inference_results_from_scenario(
    scenario: InferenceScenario,
    duration_sec: float = 5.0,
    interval_sec: float = 0.1,
) -> InferenceResults:
    """Simulate an inference monitoring session driven by a scenario.

    Collects latency samples and returns an InferenceResults dataclass
    without needing a real InferenceMonitor class — this exercises the
    results and scorer modules in integration with the scenario engine.
    """
    latencies: List[float] = []
    t0 = time.monotonic()
    while time.monotonic() - t0 < duration_sec:
        tick = time.perf_counter()
        _ = scenario.sample()
        elapsed_ms = (time.perf_counter() - tick) * 1000.0
        latencies.append(elapsed_ms)
        time.sleep(interval_sec)

    latencies.sort()
    n = len(latencies)
    p50 = latencies[int(n * 0.50)] if n else 0.0
    p95 = latencies[int(n * 0.95)] if n else 0.0
    p99 = latencies[int(n * 0.99)] if n else 0.0
    fps = n / duration_sec if duration_sec > 0 else 0.0

    return InferenceResults(
        model_path="dummy/model.onnx",
        framework="dummy",
        total_inferences=n,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        latency_p99_ms=p99,
        fps=fps,
        gpu_util_avg=None,
        gpu_mem_peak_mb=None,
        power_avg_watt=8.0,
        energy_joule=8.0 * duration_sec,
        temperature_peak_c=62.0,
        layer_profile=None,
    )


def _build_raw_metrics_from_scenario(
    scenario: InferenceScenario, t: float
) -> RawMetrics:
    """Create a RawMetrics snapshot from a scenario point."""
    point = scenario.sample(t)
    return RawMetrics(
        ts_ms=int(time.time() * 1000),
        cpu_percent=point.cpu_percent,
        mem_used_mb=point.mem_used_mb,
        mem_total_mb=4096.0,
        gpu_percent=None,
        gpu_mem_used_mb=None,
        temperature_c=point.temperature_c,
        probe_name="dummy",
        status="ok",
        latency_ms=0.01,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInferenceMonitorDummyMode:
    """test_inference_monitor_dummy_mode — run with dummy probe, verify results."""

    def test_inference_monitor_dummy_mode(self):
        scenario = make_scenario("inference", seed=42)
        results = _build_inference_results_from_scenario(
            scenario, duration_sec=3.0, interval_sec=0.05
        )

        # Basic sanity: results are populated
        assert results.total_inferences > 0, "No inferences recorded"
        assert results.fps > 0, "FPS should be positive"
        assert results.latency_p50_ms >= 0
        assert results.latency_p95_ms >= results.latency_p50_ms
        assert results.latency_p99_ms >= results.latency_p95_ms
        assert results.framework == "dummy"
        assert results.model_path == "dummy/model.onnx"

        # Power and temperature populated from our dummy session
        assert results.power_avg_watt is not None
        assert results.power_avg_watt > 0
        assert results.temperature_peak_c is not None


class TestInferenceMonitorWithAggregator:
    """test_inference_monitor_with_aggregator — feed inference data into aggregator."""

    def test_inference_monitor_with_aggregator(self):
        scenario = make_scenario("inference", seed=7)
        analyzer = AggregatorAnalyzer(window_sec=30)

        # Feed 2s of inference scenario readings at ~10Hz
        for i in range(20):
            t = i * 0.1
            raw = _build_raw_metrics_from_scenario(scenario, t)
            analyzer.ingest_metrics(raw)

        summary = analyzer.get_summary()
        assert summary.sample_count_metrics == 20, (
            f"Expected 20 metrics, got {summary.sample_count_metrics}"
        )

        # InferenceScenario targets ~75% CPU
        assert summary.cpu_avg is not None
        assert 50.0 <= summary.cpu_avg <= 100.0, (
            f"Inference scenario cpu_avg {summary.cpu_avg} outside expected range"
        )

        assert summary.mem_used_avg_mb is not None
        assert summary.mem_used_avg_mb > 0

        # Temperature should be populated (scenario provides it)
        assert summary.temp_max_c is not None

        # Timelines should have data
        assert len(summary.timeline_cpu) > 0
        assert len(summary.timeline_ts_ms) == len(summary.timeline_cpu)

    def test_scorer_with_real_summary(self):
        """Use AggregatorAnalyzer.get_summary_dict() as scorer input."""
        scenario = make_scenario("inference", seed=99)
        analyzer = AggregatorAnalyzer(window_sec=30)

        # Feed 2s of data
        for i in range(20):
            t = i * 0.1
            raw = _build_raw_metrics_from_scenario(scenario, t)
            analyzer.ingest_metrics(raw)

        summary_dict = analyzer.get_summary_dict()

        # Build scorer inputs from the summary
        scorer = DeploymentScorer()
        fps = 30.0  # Simulated inference FPS
        target_fps = 25.0
        p95_ms = 5.0  # Simulated p95 latency
        target_ms = 10.0
        peak_temp = summary_dict.get("temp_max_c") or 62.0
        avg_power = summary_dict.get("power_avg_watt") or 8.0
        budget_watt = 15.0

        score = scorer.score(
            fps=fps,
            target_fps=target_fps,
            p95_ms=p95_ms,
            target_ms=target_ms,
            peak_temp=peak_temp,
            avg_power=avg_power,
            budget_watt=budget_watt,
        )

        # Score should be in valid range
        assert 0 <= score.total <= 100, f"Score {score.total} out of range"
        assert score.verdict in ("ready", "marginal", "not_ready")

        # All four sub-scores present and in range
        for attr in ("fps_score", "latency_score", "thermal_score", "power_score"):
            val = getattr(score, attr)
            assert 0 <= val <= 100, f"{attr} = {val} out of range"

        # With good targets met, verdict should be ready
        assert score.total >= 50, (
            f"Expected decent score with targets met, got {score.total}"
        )
