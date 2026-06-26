"""Tests for LeakDetector."""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory_diagnostics.leak_detector import LeakDetector, _linear_regression
from memory_diagnostics.models import LeakAlert


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_linear(
    count: int,
    start_rss: float,
    slope_mb_per_sec: float,
    interval_ms: int = 1000,
    start_ts: int = 1_000_000,
) -> List[Tuple[float, int]]:
    """Return (rss_mb, timestamp_ms) pairs with perfect linear growth."""
    samples: List[Tuple[float, int]] = []
    for i in range(count):
        ts = start_ts + i * interval_ms
        rss = start_rss + slope_mb_per_sec * i * (interval_ms / 1000.0)
        samples.append((rss, ts))
    return samples


def _generate_constant(
    count: int,
    rss: float = 512.0,
    interval_ms: int = 1000,
    start_ts: int = 1_000_000,
) -> List[Tuple[float, int]]:
    samples: List[Tuple[float, int]] = []
    for i in range(count):
        samples.append((rss, start_ts + i * interval_ms))
    return samples


def _generate_noisy(
    count: int,
    base_rss: float = 512.0,
    noise_amplitude: float = 5.0,
    interval_ms: int = 1000,
    start_ts: int = 1_000_000,
    seed: int = 42,
) -> List[Tuple[float, int]]:
    """Random fluctuations around a fixed mean (no trend)."""
    rng = random.Random(seed)
    samples: List[Tuple[float, int]] = []
    for i in range(count):
        rss = base_rss + rng.uniform(-noise_amplitude, noise_amplitude)
        samples.append((rss, start_ts + i * interval_ms))
    return samples


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLinearRegression(unittest.TestCase):
    """Unit tests for the pure-Python linear regression helper."""

    def test_perfect_line(self) -> None:
        xs = [float(i) for i in range(10)]
        ys = [2.0 * x + 3.0 for x in xs]
        slope, intercept, r_sq = _linear_regression(xs, ys)
        self.assertAlmostEqual(slope, 2.0, places=9)
        self.assertAlmostEqual(intercept, 3.0, places=9)
        self.assertAlmostEqual(r_sq, 1.0, places=9)

    def test_two_points(self) -> None:
        slope, intercept, r_sq = _linear_regression([0.0, 1.0], [0.0, 1.0])
        self.assertAlmostEqual(slope, 1.0, places=9)
        self.assertAlmostEqual(r_sq, 1.0, places=9)

    def test_single_point_returns_zeros(self) -> None:
        slope, intercept, r_sq = _linear_regression([1.0], [1.0])
        self.assertEqual(slope, 0.0)
        self.assertEqual(r_sq, 0.0)

    def test_empty_returns_zeros(self) -> None:
        slope, intercept, r_sq = _linear_regression([], [])
        self.assertEqual(slope, 0.0)
        self.assertEqual(r_sq, 0.0)


class TestLeakDetector(unittest.TestCase):
    """Tests for the LeakDetector class."""

    def test_linear_growth_detected(self) -> None:
        """Perfectly linear RSS growth must trigger an alert."""
        detector = LeakDetector(window_size=30, r_squared_threshold=0.8, slope_threshold_mb_per_sec=0.1)
        samples = _generate_linear(30, start_rss=100.0, slope_mb_per_sec=1.0)

        alert = None
        for rss, ts in samples:
            alert = detector.observe(rss, ts)

        self.assertIsNotNone(alert)
        self.assertIsInstance(alert, LeakAlert)
        self.assertGreater(alert.r_squared, 0.99)
        self.assertGreater(alert.slope_mb_per_sec, 0.1)
        self.assertEqual(alert.sample_count, 30)

    def test_steady_state_no_alert(self) -> None:
        """Constant RSS must never produce an alert."""
        detector = LeakDetector(window_size=30)
        samples = _generate_constant(60, rss=512.0)

        for rss, ts in samples:
            alert = detector.observe(rss, ts)
            self.assertIsNone(alert)

    def test_random_noise_no_alert(self) -> None:
        """Random fluctuations without a trend must not trigger an alert."""
        detector = LeakDetector(window_size=30, r_squared_threshold=0.8, slope_threshold_mb_per_sec=0.1)
        samples = _generate_noisy(60, base_rss=512.0, noise_amplitude=5.0)

        for rss, ts in samples:
            alert = detector.observe(rss, ts)
            self.assertIsNone(alert)

    def test_r_squared_threshold(self) -> None:
        """Alert must not fire when R-squared is below the threshold."""
        detector = LeakDetector(window_size=30, r_squared_threshold=0.999, slope_threshold_mb_per_sec=0.001)

        rng = random.Random(123)
        alert = None
        for i in range(40):
            ts = 1_000_000 + i * 1000
            rss = 100.0 + 1.0 * i + rng.uniform(-2.0, 2.0)
            alert = detector.observe(rss, ts)

        # Noisy data should not achieve R-squared > 0.999
        self.assertIsNone(alert)

    def test_slope_threshold(self) -> None:
        """Alert must not fire when slope is below the threshold."""
        detector = LeakDetector(window_size=30, r_squared_threshold=0.0, slope_threshold_mb_per_sec=100.0)
        # Growth at 0.5 MB/s is below the 100 MB/s threshold
        samples = _generate_linear(40, start_rss=100.0, slope_mb_per_sec=0.5)

        alert = None
        for rss, ts in samples:
            alert = detector.observe(rss, ts)

        self.assertIsNone(alert)

    def test_window_size(self) -> None:
        """Internal deque must respect maxlen = window_size."""
        window = 10
        detector = LeakDetector(window_size=window)

        # Push 3x the window size
        for i in range(30):
            detector.observe(100.0 + i, 1_000_000 + i * 1000)

        self.assertEqual(len(detector._observations), window)

    def test_memory_efficiency(self) -> None:
        """Detector RSS must stay under 1 MB after 10 000 observations."""
        detector = LeakDetector(window_size=60)
        for i in range(10_000):
            detector.observe(float(i % 100), 1_000_000 + i * 1000)

        # The deque holds at most 60 tuples; check its size directly
        self.assertEqual(len(detector._observations), 60)
        # Approximate memory: 60 tuples * ~120 bytes each < 10 KB
        # This is well under 1 MB.  We can also check via sys.getsizeof.
        size = sys.getsizeof(detector._observations)
        self.assertLess(size, 1_048_576)  # 1 MB

    def test_alert_fields(self) -> None:
        """LeakAlert fields must be correctly populated."""
        detector = LeakDetector(window_size=20, r_squared_threshold=0.8, slope_threshold_mb_per_sec=0.01)
        samples = _generate_linear(25, start_rss=200.0, slope_mb_per_sec=2.0, start_ts=500_000)

        alert = None
        for rss, ts in samples:
            alert = detector.observe(rss, ts)

        self.assertIsNotNone(alert)
        self.assertEqual(alert.window_start_ms, 500_000 + 5 * 1000)  # 6th observation (index 5) after window fills
        self.assertEqual(alert.window_end_ms, 500_000 + 24 * 1000)
        self.assertEqual(alert.sample_count, 20)
        self.assertIsNotNone(alert.estimated_time_to_oom)
        self.assertGreater(alert.estimated_time_to_oom, 0)

    def test_alert_frozen(self) -> None:
        """LeakAlert must be immutable."""
        detector = LeakDetector(window_size=10, r_squared_threshold=0.0, slope_threshold_mb_per_sec=0.001)
        samples = _generate_linear(15, start_rss=100.0, slope_mb_per_sec=5.0)

        alert = None
        for rss, ts in samples:
            alert = detector.observe(rss, ts)

        self.assertIsNotNone(alert)
        with self.assertRaises(AttributeError):
            alert.r_squared = 0.0  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
