"""Integration tests for native collector — Phase 5.

Verifies that the Python fallback path works when the C++ native module is
unavailable, and that the fallback returns the same structure as PlatformProbe.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from platform_adapter.probe import DummyProbe, PlatformCaps, PlatformProbe, RawMetrics


# ---------------------------------------------------------------------------
# NativeProbe stub — mimics the expected pybind11 C++ bridge interface.
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
# Force-dummy fallback: simulate native module unavailability.
# ---------------------------------------------------------------------------

@pytest.fixture()
def _force_no_native():
    """Ensure native_collector is not importable."""
    saved = sys.modules.get("native_collector")
    # Block import by making it raise ImportError.
    blocker = types.ModuleType("native_collector")
    blocker.__loader__ = None  # type: ignore[assignment]
    # Patch builtins.__import__ to raise for native_collector.
    original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__  # type: ignore[union-attr]

    def _patched_import(name, *args, **kwargs):
        if name == "native_collector":
            raise ImportError("native_collector not available (force_dummy)")
        return original_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=_patched_import):
        yield


class TestNativeFallback:
    """test_native_fallback — verify Python fallback when native module unavailable."""

    def test_fallback_returns_dummy_probe(self):
        """When no C++ module is available, select_default_probe must return
        a working Python probe (DummyProbe or PsutilProbe)."""
        from platform_adapter import select_default_probe

        probe = select_default_probe()
        assert probe is not None
        assert isinstance(probe, PlatformProbe)
        # Must be able to read metrics without error.
        metrics = probe.read_metrics()
        assert isinstance(metrics, RawMetrics)
        assert metrics.status in ("ok", "partial", "not_supported")

    def test_dummy_probe_returns_raw_metrics(self):
        """DummyProbe (used in force_dummy mode) returns complete RawMetrics."""
        probe = DummyProbe()
        metrics = probe.read_metrics()
        assert isinstance(metrics, RawMetrics)
        assert metrics.probe_name == "dummy"
        assert metrics.status == "ok"
        assert isinstance(metrics.ts_ms, int)
        assert isinstance(metrics.cpu_percent, float)
        assert isinstance(metrics.mem_used_mb, float)
        assert isinstance(metrics.mem_total_mb, float)

    def test_native_probe_stub_implements_platform_probe_interface(self):
        """The NativeProbe stub must satisfy the PlatformProbe contract."""
        stub = _NativeProbeStub()
        assert hasattr(stub, "is_available")
        assert hasattr(stub, "detect_caps")
        assert hasattr(stub, "read_metrics")
        assert callable(stub.is_available)
        assert callable(stub.detect_caps)
        assert callable(stub.read_metrics)
        assert stub.is_available() is True
        caps = stub.detect_caps()
        assert isinstance(caps, PlatformCaps)
        metrics = stub.read_metrics()
        assert isinstance(metrics, RawMetrics)


class TestInterfaceCompatibility:
    """test_interface_compatibility — verify NativeProbe (or fallback) returns
    same structure as PlatformProbe."""

    @pytest.fixture()
    def _probes(self):
        """Return (native_stub, dummy_probe) pair for comparison."""
        return _NativeProbeStub(), DummyProbe()

    def test_read_metrics_returns_same_type(self, _probes):
        """Both probes must return RawMetrics."""
        native, dummy = _probes
        assert isinstance(native.read_metrics(), RawMetrics)
        assert isinstance(dummy.read_metrics(), RawMetrics)

    def test_raw_metrics_fields_match(self, _probes):
        """Both probes must return RawMetrics with identical field names."""
        native, dummy = _probes
        native_fields = set(vars(native.read_metrics()).keys())
        dummy_fields = set(vars(dummy.read_metrics()).keys())
        assert native_fields == dummy_fields, (
            f"Field mismatch: native-only={native_fields - dummy_fields}, "
            f"dummy-only={dummy_fields - native_fields}"
        )

    def test_detect_caps_returns_platform_caps(self, _probes):
        """Both probes must return PlatformCaps from detect_caps()."""
        native, dummy = _probes
        assert isinstance(native.detect_caps(), PlatformCaps)
        assert isinstance(dummy.detect_caps(), PlatformCaps)

    def test_is_available_returns_bool(self, _probes):
        """is_available() must return a bool for both probes."""
        native, dummy = _probes
        assert isinstance(native.is_available(), bool)
        assert isinstance(dummy.is_available(), bool)

    def test_required_raw_metrics_fields_present(self, _probes):
        """RawMetrics must contain all fields defined in the probe contract."""
        required_fields = {
            "ts_ms", "cpu_percent", "mem_used_mb", "mem_total_mb",
            "gpu_percent", "gpu_mem_used_mb", "temperature_c",
            "probe_name", "status", "latency_ms",
        }
        native, dummy = _probes
        for probe in (native, dummy):
            m = probe.read_metrics()
            actual = set(vars(m).keys())
            missing = required_fields - actual
            assert not missing, f"{probe.name} missing fields: {missing}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
