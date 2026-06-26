"""Tests for native_collector Python wrapper and fallback logic."""

from __future__ import annotations

import sys

import pytest


def test_import_does_not_crash():
    """Importing native_collector must succeed on any platform."""
    import native_collector  # noqa: F401


def test_has_native_false_on_windows():
    """On Windows there is no compiled .so/.pyd, so HAS_NATIVE is False."""
    if sys.platform == "win32":
        from native_collector import HAS_NATIVE

        assert HAS_NATIVE is False


def test_select_probe_returns_python_probe():
    """select_probe() without force_native returns a Python-based probe."""
    from native_collector import select_probe

    probe = select_probe()
    # Should have a read_metrics method (PlatformProbe interface)
    assert hasattr(probe, "read_metrics")


def test_select_probe_force_native_raises():
    """force_native=True must raise ImportError when native module is absent."""
    from native_collector import HAS_NATIVE, select_probe

    if HAS_NATIVE:
        pytest.skip("Native module is available; cannot test ImportError path")

    with pytest.raises(ImportError, match="Native collector not available"):
        select_probe(force_native=True)
