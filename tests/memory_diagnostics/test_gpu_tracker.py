"""Tests for GpuMemoryTracker — 4 correlation patterns + edge cases."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from memory_diagnostics.gpu_tracker import GpuLeakAlert, GpuMemoryTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rising(start: float, step: float, count: int) -> list[float]:
    """Return a list of linearly increasing values."""
    return [start + step * i for i in range(count)]


def _make_constant(value: float, count: int) -> list[float]:
    """Return a list of constant values."""
    return [value] * count


def _timestamps(count: int, interval_ms: int = 1000) -> list[int]:
    """Return evenly spaced timestamps starting at 0."""
    return [i * interval_ms for i in range(count)]


def _feed(
    tracker: GpuMemoryTracker,
    rss_values: list[float],
    gpu_values: list[None | float],
    timestamps: list[int],
):
    """Feed a sequence of observations into *tracker*, returning the last result."""
    result = None
    for rss, gpu, ts in zip(rss_values, gpu_values, timestamps):
        result = tracker.observe(rss, gpu, ts)
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDualLeak:
    """Both RSS and GPU growing — expect CRITICAL alert."""

    def test_dual_leak(self) -> None:
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        n = 20
        rss = _make_rising(100.0, 1.0, n)
        gpu = _make_rising(200.0, 0.5, n)
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)

        assert alert is not None
        assert alert.severity == "CRITICAL"
        assert alert.pattern == "dual_leak"
        assert alert.cpu_leak_detected is True
        assert alert.gpu_leak_detected is True
        assert alert.cpu_slope > 0
        assert alert.gpu_slope > 0


class TestCpuOnlyLeak:
    """RSS growing, GPU stable — expect WARNING with cpu_only_leak pattern."""

    def test_cpu_only_leak(self) -> None:
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        n = 20
        rss = _make_rising(100.0, 1.0, n)
        gpu = _make_constant(512.0, n)
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)

        assert alert is not None
        assert alert.severity == "WARNING"
        assert alert.pattern == "cpu_only_leak"
        assert alert.cpu_leak_detected is True
        assert alert.gpu_leak_detected is False
        assert alert.cpu_slope > 0


class TestGpuOnlyLeak:
    """RSS stable, GPU growing — expect WARNING with gpu_only_leak pattern."""

    def test_gpu_only_leak(self) -> None:
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        n = 20
        rss = _make_constant(100.0, n)
        gpu = _make_rising(200.0, 0.5, n)
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)

        assert alert is not None
        assert alert.severity == "WARNING"
        assert alert.pattern == "gpu_only_leak"
        assert alert.cpu_leak_detected is False
        assert alert.gpu_leak_detected is True
        assert alert.gpu_slope > 0


class TestNoLeak:
    """Both stable — expect None."""

    def test_no_leak(self) -> None:
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        n = 20
        rss = _make_constant(100.0, n)
        gpu = _make_constant(512.0, n)
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)

        assert alert is None


class TestNoneGpuData:
    """gpu_mem_mb=None — falls back to CPU-only analysis."""

    def test_none_gpu_data_cpu_leak(self) -> None:
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        n = 20
        rss = _make_rising(100.0, 1.0, n)
        gpu = [None] * n
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)

        assert alert is not None
        assert alert.severity == "WARNING"
        assert alert.pattern == "cpu_only_leak"
        assert alert.cpu_leak_detected is True
        assert alert.gpu_leak_detected is False

    def test_none_gpu_data_no_leak(self) -> None:
        """Stable RSS with no GPU data should produce no alert."""
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        n = 20
        rss = _make_constant(100.0, n)
        gpu = [None] * n
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)

        assert alert is None


class TestInsufficientData:
    """Fewer than 5 observations — expect None."""

    def test_insufficient_data_returns_none(self) -> None:
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)

        for count in range(0, 5):
            sub = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)
            rss = _make_rising(100.0, 10.0, count)
            gpu = _make_rising(200.0, 10.0, count)
            ts = _timestamps(count)

            result = _feed(sub, rss, gpu, ts)
            assert result is None, f"Expected None for {count} samples, got {result}"

    def test_exactly_five_can_alert(self) -> None:
        """With exactly 5 samples showing a strong trend, an alert may fire."""
        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.3)

        n = 5
        rss = _make_rising(100.0, 10.0, n)
        gpu = _make_rising(200.0, 10.0, n)
        ts = _timestamps(n)

        alert = _feed(tracker, rss, gpu, ts)
        # With 5 perfect linear points and a low threshold, should detect.
        assert alert is not None
        assert alert.severity == "CRITICAL"
