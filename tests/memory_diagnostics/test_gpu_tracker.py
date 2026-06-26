"""Tests for GpuMemoryTracker -- 4 correlation patterns + edge cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory_diagnostics.gpu_tracker import GpuLeakAlert, GpuMemoryTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rising(start: float, step: float, count: int) -> list:
    """Return a list of linearly increasing values."""
    return [start + step * i for i in range(count)]


def _make_constant(value: float, count: int) -> list:
    """Return a list of constant values."""
    return [value] * count


def _timestamps(count: int, interval_ms: int = 1000) -> list:
    """Return evenly spaced timestamps starting at 0."""
    return [i * interval_ms for i in range(count)]


def _feed(
    tracker: GpuMemoryTracker,
    rss_values: list,
    gpu_values: list,
    timestamps: list,
):
    """Feed a sequence of observations into *tracker*, returning the last result."""
    result = None
    for rss, gpu, ts in zip(rss_values, gpu_values, timestamps):
        result = tracker.observe(rss, gpu, ts)
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDualLeak(unittest.TestCase):
    """Both RSS and GPU growing -- expect CRITICAL alert."""

    def test_dual_leak(self) -> None:
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        n = 20
        rss = _make_rising(100.0, 1.0, n)
        gpu = _make_rising(200.0, 0.5, n)
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "CRITICAL")
        self.assertEqual(alert.pattern, "dual_leak")
        self.assertTrue(alert.cpu_leak_detected)
        self.assertTrue(alert.gpu_leak_detected)
        self.assertGreater(alert.cpu_slope, 0)
        self.assertGreater(alert.gpu_slope, 0)


class TestCpuOnlyLeak(unittest.TestCase):
    """RSS growing, GPU stable -- expect WARNING with cpu_only_leak pattern."""

    def test_cpu_only_leak(self) -> None:
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        n = 20
        rss = _make_rising(100.0, 1.0, n)
        gpu = _make_constant(512.0, n)
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "WARNING")
        self.assertEqual(alert.pattern, "cpu_only_leak")
        self.assertTrue(alert.cpu_leak_detected)
        self.assertFalse(alert.gpu_leak_detected)
        self.assertGreater(alert.cpu_slope, 0)


class TestGpuOnlyLeak(unittest.TestCase):
    """RSS stable, GPU growing -- expect WARNING with gpu_only_leak pattern."""

    def test_gpu_only_leak(self) -> None:
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        n = 20
        rss = _make_constant(100.0, n)
        gpu = _make_rising(200.0, 0.5, n)
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "WARNING")
        self.assertEqual(alert.pattern, "gpu_only_leak")
        self.assertFalse(alert.cpu_leak_detected)
        self.assertTrue(alert.gpu_leak_detected)
        self.assertGreater(alert.gpu_slope, 0)


class TestNoLeak(unittest.TestCase):
    """Both stable -- expect None."""

    def test_no_leak(self) -> None:
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        n = 20
        rss = _make_constant(100.0, n)
        gpu = _make_constant(512.0, n)
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)

        self.assertIsNone(alert)


class TestNoneGpuData(unittest.TestCase):
    """gpu_mem_mb=None -- falls back to CPU-only analysis."""

    def test_none_gpu_data_cpu_leak(self) -> None:
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        n = 20
        rss = _make_rising(100.0, 1.0, n)
        gpu = [None] * n
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "WARNING")
        self.assertEqual(alert.pattern, "cpu_only_leak")
        self.assertTrue(alert.cpu_leak_detected)
        self.assertFalse(alert.gpu_leak_detected)

    def test_none_gpu_data_no_leak(self) -> None:
        """Stable RSS with no GPU data should produce no alert."""
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        n = 20
        rss = _make_constant(100.0, n)
        gpu = [None] * n
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)

        self.assertIsNone(alert)


class TestInsufficientData(unittest.TestCase):
    """Fewer than 5 observations -- expect None."""

    def test_insufficient_data_returns_none(self) -> None:
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        for count in range(0, 5):
            sub = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)
            rss = _make_rising(100.0, 10.0, count)
            gpu = _make_rising(200.0, 10.0, count)
            ts = _timestamps(count)

            result = _feed(sub, rss, gpu, ts)
            self.assertIsNone(result, f"Expected None for {count} samples, got {result}")

    def test_exactly_five_can_alert(self) -> None:
        """With exactly 5 samples showing a strong trend, an alert may fire."""
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.3)

        n = 5
        rss = _make_rising(100.0, 10.0, n)
        gpu = _make_rising(200.0, 10.0, n)
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)
        # With 5 perfect linear points and a low threshold, should detect.
        self.assertIsNotNone(alert)
        self.assertEqual(alert.severity, "CRITICAL")


if __name__ == "__main__":
    unittest.main()
