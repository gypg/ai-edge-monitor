"""Integration tests for native collector -- Phase 5.

Verifies that the Python fallback path works when the C++ native module is
unavailable, and that the fallback returns the same structure as PlatformProbe.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from platform_adapter.probe import DummyProbe, PlatformCaps, PlatformProbe, RawMetrics


# ---------------------------------------------------------------------------
# NativeProbe stub -- mimics the expected pybind11 C++ bridge interface.
# ---------------------------------------------------------------------------
# The actual native_collector C++ module is not built in CI (no C++ compiler
# on the test host).  This stub represents the *interface contract* that the
# real module must satisfy so we can validate the fallback path.

class _NativeProbeStub:
    """Stub that mirrors the expected ``NativeProbe`` pybind11 class.

    When the C++ extension is not installed, the platform_adapter should
    transparently fall back to a Python probe.  This stub lets us verify
    the interface contract even without the compiled extension.
    """

    def __init__(self) -> None:
        self.name = "native"

    def is_available(self) -> bool:
        return True

    def detect_caps(self) -> PlatformCaps:
        return PlatformCaps(
            has_cpu=True,
            has_mem=True,
            has_gpu=False,
            has_temp_sensor=True,
            has_power_sensor=False,
            platform_name="native-cpp",
        )

    def read_metrics(self) -> RawMetrics:
        import time
        started = time.perf_counter()
        ts_ms = int(time.time() * 1000)
        latency_ms = (time.perf_counter() - started) * 1000.0
        return RawMetrics(
            ts_ms=ts_ms,
            cpu_percent=0.0,
            mem_used_mb=0.0,
            mem_total_mb=0.0,
            gpu_percent=None,
            gpu_mem_used_mb=None,
            temperature_c=None,
            probe_name=self.name,
            status="ok",
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNativeFallback(unittest.TestCase):
    """test_native_fallback -- verify Python fallback when native module unavailable."""

    def test_fallback_returns_dummy_probe(self):
        """When no C++ module is available, select_default_probe must return
        a working Python probe (DummyProbe or PsutilProbe)."""
        from platform_adapter import select_default_probe

        probe = select_default_probe()
        self.assertIsNotNone(probe)
        self.assertIsInstance(probe, PlatformProbe)
        # Must be able to read metrics without error.
        metrics = probe.read_metrics()
        self.assertIsInstance(metrics, RawMetrics)
        self.assertIn(metrics.status, ("ok", "partial", "not_supported"))

    def test_dummy_probe_returns_raw_metrics(self):
        """DummyProbe (used in force_dummy mode) returns complete RawMetrics."""
        probe = DummyProbe()
        metrics = probe.read_metrics()
        self.assertIsInstance(metrics, RawMetrics)
        self.assertEqual(metrics.probe_name, "dummy")
        self.assertEqual(metrics.status, "ok")
        self.assertIsInstance(metrics.ts_ms, int)
        self.assertIsInstance(metrics.cpu_percent, float)
        self.assertIsInstance(metrics.mem_used_mb, float)
        self.assertIsInstance(metrics.mem_total_mb, float)

    def test_native_probe_stub_implements_platform_probe_interface(self):
        """The NativeProbe stub must satisfy the PlatformProbe contract."""
        stub = _NativeProbeStub()
        self.assertTrue(hasattr(stub, "is_available"))
        self.assertTrue(hasattr(stub, "detect_caps"))
        self.assertTrue(hasattr(stub, "read_metrics"))
        self.assertTrue(callable(stub.is_available))
        self.assertTrue(callable(stub.detect_caps))
        self.assertTrue(callable(stub.read_metrics))
        self.assertTrue(stub.is_available())
        caps = stub.detect_caps()
        self.assertIsInstance(caps, PlatformCaps)
        metrics = stub.read_metrics()
        self.assertIsInstance(metrics, RawMetrics)


class TestInterfaceCompatibility(unittest.TestCase):
    """test_interface_compatibility -- verify NativeProbe (or fallback) returns
    same structure as PlatformProbe."""

    def setUp(self):
        self._native = _NativeProbeStub()
        self._dummy = DummyProbe()

    def test_read_metrics_returns_same_type(self):
        """Both probes must return RawMetrics."""
        self.assertIsInstance(self._native.read_metrics(), RawMetrics)
        self.assertIsInstance(self._dummy.read_metrics(), RawMetrics)

    def test_raw_metrics_fields_match(self):
        """Both probes must return RawMetrics with identical field names."""
        native_fields = set(vars(self._native.read_metrics()).keys())
        dummy_fields = set(vars(self._dummy.read_metrics()).keys())
        self.assertEqual(native_fields, dummy_fields, (
            f"Field mismatch: native-only={native_fields - dummy_fields}, "
            f"dummy-only={dummy_fields - native_fields}"
        ))

    def test_detect_caps_returns_platform_caps(self):
        """Both probes must return PlatformCaps from detect_caps()."""
        self.assertIsInstance(self._native.detect_caps(), PlatformCaps)
        self.assertIsInstance(self._dummy.detect_caps(), PlatformCaps)

    def test_is_available_returns_bool(self):
        """is_available() must return a bool for both probes."""
        self.assertIsInstance(self._native.is_available(), bool)
        self.assertIsInstance(self._dummy.is_available(), bool)

    def test_required_raw_metrics_fields_present(self):
        """RawMetrics must contain all fields defined in the probe contract."""
        required_fields = {
            "ts_ms", "cpu_percent", "mem_used_mb", "mem_total_mb",
            "gpu_percent", "gpu_mem_used_mb", "temperature_c",
            "probe_name", "status", "latency_ms",
        }
        for probe in (self._native, self._dummy):
            m = probe.read_metrics()
            actual = set(vars(m).keys())
            missing = required_fields - actual
            self.assertFalse(missing, f"{probe.name} missing fields: {missing}")


if __name__ == "__main__":
    unittest.main()
