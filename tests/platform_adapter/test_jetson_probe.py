"""Tests for JetsonProbe.

These tests exercise the non-hardware logic paths.  jtop and tegrastats are
not available in CI, so every test runs with the probe in the
``unavailable`` state and verifies graceful fallback.

This module uses only stdlib assertions so it can be run directly with
``python tests/platform_adapter/test_jetson_probe.py`` in CI environments
that do not have pytest installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from platform_adapter import JetsonProbe  # noqa: E402


def test_jetson_probe_unavailable_on_non_jetson() -> None:
    probe = JetsonProbe()
    assert not probe.is_available()
    assert not probe.detect_caps().has_gpu


def test_jetson_probe_read_metrics_returns_not_supported() -> None:
    probe = JetsonProbe()
    metrics = probe.read_metrics()
    assert metrics.probe_name == "jetson"
    assert metrics.status == "not_supported"
    assert metrics.gpu_percent is None
    assert metrics.gpu_mem_used_mb is None
    assert metrics.error_message is not None


def test_jetson_probe_close_is_safe() -> None:
    probe = JetsonProbe()
    probe.close()  # should not raise even when no resources are held


if __name__ == "__main__":
    test_jetson_probe_unavailable_on_non_jetson()
    test_jetson_probe_read_metrics_returns_not_supported()
    test_jetson_probe_close_is_safe()
    print("OK")
