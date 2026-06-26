"""Tests for TensorRT profiler bridge (Python 3.8+).

Covers:
- Recording of layer times via report_layer_time
- Total time aggregation
- Empty profiler behaviour
- Graceful fallback when tensorrt is unavailable

All tests run without an actual TensorRT installation -- the
``tensorrt`` import is either unavailable (natural on CI / dev
machines) or mocked via ``unittest.mock``.
"""

from __future__ import annotations

import logging
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

# ---------------------------------------------------------------------------
# Ensure ``src/`` is on sys.path so inference_monitor resolves correctly
# (same pattern as tests/platform_adapter/test_baseline.py).
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ---------------------------------------------------------------------------
# Import the module under test -- works regardless of whether tensorrt is
# installed because the bridge itself handles ImportError.
# ---------------------------------------------------------------------------

from inference_monitor.tensorrt_bridge import (
    HAS_TENSORRT,
    LayerProfile,
    TensorRTProfiler,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProfilerRecordsLayers(unittest.TestCase):
    """report_layer_time captures per-layer execution data."""

    def test_profiler_records_layers(self) -> None:
        profiler = TensorRTProfiler()

        # Simulate two inferences with two layers
        profiler.report_layer_time("conv1", 1.2)
        profiler.report_layer_time("relu1", 0.3)
        profiler.report_layer_time("conv1", 1.4)
        profiler.report_layer_time("relu1", 0.5)

        profiles = profiler.get_layer_profiles()
        self.assertEqual(len(profiles), 2)

        by_name = {p.name: p for p in profiles}

        self.assertEqual(by_name["conv1"].calls, 2)
        self.assertAlmostEqual(by_name["conv1"].avg_time_ms, 1.3)

        self.assertEqual(by_name["relu1"].calls, 2)
        self.assertAlmostEqual(by_name["relu1"].avg_time_ms, 0.4)

    def test_profiler_layers_sorted_by_name(self) -> None:
        profiler = TensorRTProfiler()
        profiler.report_layer_time("z_layer", 1.0)
        profiler.report_layer_time("a_layer", 2.0)

        names = [p.name for p in profiler.get_layer_profiles()]
        self.assertEqual(names, sorted(names))

    def test_layer_profile_is_frozen(self) -> None:
        """LayerProfile is an immutable dataclass."""
        profiler = TensorRTProfiler()
        profiler.report_layer_time("conv", 1.0)
        profile = profiler.get_layer_profiles()[0]
        self.assertEqual(type(profile).__name__, "LayerProfile")
        with self.assertRaises(AttributeError):
            profile.name = "changed"  # type: ignore[misc]


class TestProfilerTotalTime(unittest.TestCase):
    """get_total_time_ms returns the sum of all layer times."""

    def test_profiler_total_time(self) -> None:
        profiler = TensorRTProfiler()
        profiler.report_layer_time("conv1", 1.2)
        profiler.report_layer_time("relu1", 0.3)
        profiler.report_layer_time("conv1", 1.4)
        profiler.report_layer_time("relu1", 0.5)

        self.assertAlmostEqual(profiler.get_total_time_ms(), 3.4)

    def test_total_time_single_layer(self) -> None:
        profiler = TensorRTProfiler()
        profiler.report_layer_time("only", 5.0)
        self.assertAlmostEqual(profiler.get_total_time_ms(), 5.0)


class TestProfilerEmpty(unittest.TestCase):
    """Empty profiler returns sensible defaults."""

    def test_profiler_empty(self) -> None:
        profiler = TensorRTProfiler()

        self.assertEqual(profiler.get_layer_profiles(), [])
        self.assertEqual(profiler.get_total_time_ms(), 0.0)

    def test_reset_clears_data(self) -> None:
        profiler = TensorRTProfiler()
        profiler.report_layer_time("conv", 1.0)
        profiler.reset()

        self.assertEqual(profiler.get_layer_profiles(), [])
        self.assertEqual(profiler.get_total_time_ms(), 0.0)


class TestImportFallback(unittest.TestCase):
    """Verify graceful degradation when tensorrt is not installed."""

    def test_import_fallback_module_loads(self) -> None:
        """The module must always importable regardless of tensorrt."""
        # If we got here, the import at module top succeeded -- that's the test.
        self.assertIsNotNone(TensorRTProfiler)

    def test_import_fallback_profiler_is_noop(self) -> None:
        """When HAS_TENSORRT is False the profiler still works as a no-op."""
        if HAS_TENSORRT:
            self.skipTest("tensorrt is installed; cannot test fallback path")

        profiler = TensorRTProfiler()
        # Should not raise, and should produce empty results
        self.assertEqual(profiler.get_layer_profiles(), [])
        self.assertEqual(profiler.get_total_time_ms(), 0.0)

        # report_layer_time still works (records data locally)
        profiler.report_layer_time("test_layer", 1.5)
        self.assertEqual(len(profiler.get_layer_profiles()), 1)

    def test_import_fallback_logs_warning(self) -> None:
        """First use in no-TensorRT mode logs a WARNING."""
        if HAS_TENSORRT:
            self.skipTest("tensorrt is installed; cannot test fallback path")

        profiler = TensorRTProfiler()
        with self.assertLogs("inference_monitor.tensorrt_bridge", level=logging.WARNING) as cm:
            profiler.report_layer_time("layer", 0.1)

        self.assertTrue(any("TensorRT not available" in msg for msg in cm.output))

    def test_warning_only_once(self) -> None:
        """The no-TensorRT warning is emitted only on the first call."""
        if HAS_TENSORRT:
            self.skipTest("tensorrt is installed; cannot test fallback path")

        profiler = TensorRTProfiler()
        with self.assertLogs("inference_monitor.tensorrt_bridge", level=logging.WARNING) as cm:
            profiler.report_layer_time("a", 0.1)
            profiler.report_layer_time("b", 0.2)

        trt_warnings = [m for m in cm.output if "TensorRT not available" in m]
        self.assertEqual(len(trt_warnings), 1)

    def test_import_fallback_with_mock(self) -> None:
        """Simulate tensorrt being unavailable by reloading with a blocked import."""
        import importlib

        import inference_monitor.tensorrt_bridge as mod

        original_trt = sys.modules.get("tensorrt")
        # Ensure tensorrt is NOT importable
        sys.modules["tensorrt"] = None  # type: ignore[assignment]
        try:
            reloaded = importlib.reload(mod)
            self.assertFalse(reloaded.HAS_TENSORRT)

            profiler = reloaded.TensorRTProfiler()
            profiler.report_layer_time("mocked_layer", 2.5)
            profiles = profiler.get_layer_profiles()
            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0].name, "mocked_layer")
            self.assertAlmostEqual(profiles[0].avg_time_ms, 2.5)
        finally:
            # Restore original state
            if original_trt is not None:
                sys.modules["tensorrt"] = original_trt
            else:
                sys.modules.pop("tensorrt", None)
            importlib.reload(mod)


if __name__ == "__main__":
    unittest.main()
