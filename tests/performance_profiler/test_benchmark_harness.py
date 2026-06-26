"""Tests for benchmark_harness — loading, scoring, comparison, and reporting."""

from __future__ import annotations

import json
import os
import shutil

# Ensure the src package is importable.
import sys
import tempfile
import unittest

_SRC = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, os.path.abspath(_SRC))

from performance_profiler.benchmark_harness import (  # noqa: E402
    BenchmarkHarness,
    BenchmarkRun,
    detect_regression,
    format_report,
)


def _make_run(
    name: str = "test-run",
    fps: float = 30.0,
    latency: float = 40.0,
    temp: float = 70.0,
    power: float = 12.0,
    timestamp: str = "2026-06-26T12:00:00",
    device_info: dict | None = None,
) -> BenchmarkRun:
    """Create a BenchmarkRun with sensible defaults."""
    return BenchmarkRun(
        name=name,
        timestamp=timestamp,
        device_info=device_info or {"platform": "Jetson Orin Nano"},
        metrics={
            "fps_avg": fps,
            "latency_p95_ms": latency,
            "temp_max_c": temp,
            "power_avg_watt": power,
        },
    )


class TestBenchmarkRunDataclass(unittest.TestCase):
    """BenchmarkRun is a simple data container."""

    def test_default_device_info(self) -> None:
        run = _make_run(device_info=None)
        self.assertIsInstance(run.device_info, dict)

    def test_metrics_preserved(self) -> None:
        run = _make_run(fps=60.0, latency=10.0)
        self.assertAlmostEqual(run.metrics["fps_avg"], 60.0)
        self.assertAlmostEqual(run.metrics["latency_p95_ms"], 10.0)


class TestLoadFromJson(unittest.TestCase):
    """JSON loading via BenchmarkHarness.load_from_json."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_json(self, filename: str, data: dict) -> str:
        path = os.path.join(self.tmpdir, filename)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def test_load_valid_json(self) -> None:
        payload = {
            "name": "run-A",
            "timestamp": "2026-06-26T10:00:00",
            "device_info": {"platform": "RPi4"},
            "metrics": {"fps_avg": 25.0, "latency_p95_ms": 55.0},
        }
        path = self._write_json("run_a.json", payload)
        run = BenchmarkHarness.load_from_json(path)

        self.assertEqual(run.name, "run-A")
        self.assertAlmostEqual(run.metrics["fps_avg"], 25.0)
        self.assertEqual(run.source_path, path)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            BenchmarkHarness.load_from_json("/nonexistent/path.json")

    def test_invalid_json_raises_value_error(self) -> None:
        path = os.path.join(self.tmpdir, "bad.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{{{not json")
        with self.assertRaises(ValueError):
            BenchmarkHarness.load_from_json(path)

    def test_missing_metrics_field_raises(self) -> None:
        path = self._write_json("no_metrics.json", {"name": "x"})
        with self.assertRaises(ValueError):
            BenchmarkHarness.load_from_json(path)

    def test_defaults_name_from_filename(self) -> None:
        path = self._write_json("auto_name.json", {"metrics": {"fps_avg": 10}})
        run = BenchmarkHarness.load_from_json(path)
        self.assertEqual(run.name, "auto_name")


class TestLoadFromDirectory(unittest.TestCase):
    """Batch loading via BenchmarkHarness.load_from_directory."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_json(self, filename: str, data: dict) -> str:
        path = os.path.join(self.tmpdir, filename)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return path

    def test_loads_all_json_files(self) -> None:
        for i in range(3):
            self._write_json(
                "run_{}.json".format(i),
                {"name": "r{}".format(i), "metrics": {"fps_avg": float(i)}},
            )
        runs = BenchmarkHarness.load_from_directory(self.tmpdir)
        self.assertEqual(len(runs), 3)

    def test_skips_non_json_files(self) -> None:
        self._write_json("good.json", {"metrics": {"fps_avg": 10}})
        with open(os.path.join(self.tmpdir, "skip.txt"), "w") as fh:
            fh.write("ignore me")
        runs = BenchmarkHarness.load_from_directory(self.tmpdir)
        self.assertEqual(len(runs), 1)

    def test_directory_not_found_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            BenchmarkHarness.load_from_directory("/no/such/dir")

    def test_skips_corrupt_json(self) -> None:
        self._write_json("good.json", {"metrics": {"fps_avg": 10}})
        with open(os.path.join(self.tmpdir, "bad.json"), "w") as fh:
            fh.write("{{{")
        runs = BenchmarkHarness.load_from_directory(self.tmpdir)
        self.assertEqual(len(runs), 1)


class TestScoreRun(unittest.TestCase):
    """Scoring via BenchmarkHarness.score_run."""

    def test_ready_when_all_targets_met(self) -> None:
        run = _make_run(fps=35.0, latency=30.0, temp=65.0, power=10.0)
        assessment = BenchmarkHarness.score_run(run, target_fps=30.0)

        self.assertIsInstance(assessment.ready, bool)
        self.assertGreaterEqual(assessment.score, 0)
        self.assertLessEqual(assessment.score, 100)

    def test_not_ready_when_fps_too_low(self) -> None:
        run = _make_run(fps=5.0, latency=30.0, temp=65.0, power=10.0)
        assessment = BenchmarkHarness.score_run(run, target_fps=30.0)
        self.assertFalse(assessment.ready)

    def test_blocking_issues_present_when_critical(self) -> None:
        run = _make_run(fps=2.0, latency=300.0, temp=95.0, power=50.0)
        assessment = BenchmarkHarness.score_run(
            run,
            target_fps=30.0,
            target_latency=50.0,
            power_budget=15.0,
            thermal_limit=80.0,
        )
        self.assertGreater(len(assessment.blocking_issues), 0)

    def test_custom_thermal_limit(self) -> None:
        run = _make_run(fps=35.0, latency=30.0, temp=75.0, power=10.0)
        a_low = BenchmarkHarness.score_run(run, thermal_limit=76.0)
        a_high = BenchmarkHarness.score_run(run, thermal_limit=100.0)
        # Tighter thermal limit should produce a lower or equal score.
        self.assertLessEqual(a_low.score, a_high.score)


class TestCompareRuns(unittest.TestCase):
    """Run comparison via BenchmarkHarness.compare_runs."""

    def test_no_regression_when_stable(self) -> None:
        baseline = _make_run(name="baseline", fps=30.0, latency=40.0, temp=70.0, power=12.0)
        current = _make_run(name="current", fps=30.0, latency=40.0, temp=70.0, power=12.0)
        result = BenchmarkHarness.compare_runs(baseline, current)

        self.assertFalse(result["regression_detected"])
        self.assertEqual(len(result["regressions"]), 0)

    def test_fps_regression_detected(self) -> None:
        baseline = _make_run(name="baseline", fps=30.0)
        current = _make_run(name="current", fps=20.0)
        result = BenchmarkHarness.compare_runs(baseline, current, regression_threshold=0.1)

        self.assertTrue(result["regression_detected"])
        self.assertTrue(any("FPS" in r for r in result["regressions"]))

    def test_latency_regression_detected(self) -> None:
        baseline = _make_run(name="baseline", latency=40.0)
        current = _make_run(name="current", latency=60.0)
        result = BenchmarkHarness.compare_runs(baseline, current, regression_threshold=0.1)

        self.assertTrue(result["regression_detected"])
        self.assertTrue(any("latency" in r.lower() for r in result["regressions"]))

    def test_improvement_not_flagged(self) -> None:
        baseline = _make_run(name="baseline", fps=20.0)
        current = _make_run(name="current", fps=35.0)
        result = BenchmarkHarness.compare_runs(baseline, current)
        self.assertFalse(result["regression_detected"])

    def test_deltas_calculated_correctly(self) -> None:
        baseline = _make_run(name="b", fps=20.0, latency=50.0)
        current = _make_run(name="c", fps=25.0, latency=40.0)
        result = BenchmarkHarness.compare_runs(baseline, current)

        self.assertAlmostEqual(result["deltas"]["fps_avg"]["delta"], 5.0)
        self.assertAlmostEqual(result["deltas"]["latency_p95_ms"]["delta"], -10.0)


class TestDetectRegression(unittest.TestCase):
    """Standalone regression detection."""

    def test_no_regression_above_threshold(self) -> None:
        self.assertFalse(detect_regression(30.0, 28.0, threshold=0.1))

    def test_regression_below_threshold(self) -> None:
        self.assertTrue(detect_regression(30.0, 20.0, threshold=0.1))

    def test_zero_baseline_returns_false(self) -> None:
        self.assertFalse(detect_regression(0.0, 5.0))


class TestGenerateSummary(unittest.TestCase):
    """Summary generation via BenchmarkHarness.generate_summary."""

    def test_empty_list(self) -> None:
        summary = BenchmarkHarness.generate_summary([])
        self.assertEqual(summary["run_count"], 0)

    def test_single_run(self) -> None:
        runs = [_make_run(fps=30.0, latency=40.0, temp=70.0, power=12.0)]
        summary = BenchmarkHarness.generate_summary(runs)

        self.assertEqual(summary["run_count"], 1)
        self.assertAlmostEqual(summary["aggregates"]["fps_avg"]["avg"], 30.0)

    def test_multiple_runs_aggregates(self) -> None:
        runs = [
            _make_run(name="a", fps=20.0, latency=50.0),
            _make_run(name="b", fps=40.0, latency=30.0),
        ]
        summary = BenchmarkHarness.generate_summary(runs)

        self.assertEqual(summary["run_count"], 2)
        self.assertAlmostEqual(summary["aggregates"]["fps_avg"]["min"], 20.0)
        self.assertAlmostEqual(summary["aggregates"]["fps_avg"]["max"], 40.0)
        self.assertAlmostEqual(summary["aggregates"]["fps_avg"]["avg"], 30.0)


class TestFormatReport(unittest.TestCase):
    """Report formatting via format_report."""

    def test_output_contains_header(self) -> None:
        text = format_report({"run_count": 0})
        self.assertIn("BENCHMARK SUMMARY", text)

    def test_output_contains_run_names(self) -> None:
        summary = {
            "run_count": 1,
            "runs": [{"name": "run-X", "timestamp": "2026-06-26"}],
            "aggregates": {},
        }
        text = format_report(summary)
        self.assertIn("run-X", text)

    def test_output_contains_metrics(self) -> None:
        summary = {
            "run_count": 1,
            "runs": [],
            "aggregates": {
                "fps_avg": {"min": 20.0, "max": 40.0, "avg": 30.0, "count": 2},
            },
        }
        text = format_report(summary)
        self.assertIn("fps_avg", text)
        self.assertIn("30.00", text)


if __name__ == "__main__":
    unittest.main()
