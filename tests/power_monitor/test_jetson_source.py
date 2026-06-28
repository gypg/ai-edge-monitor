"""Tests for JetsonPowerSource.

Verifies that the Jetson power source correctly reports unavailability when
jtop/tegrastats are absent and that the public contract (is_available,
read_once) behaves like any other PowerSource.

This module uses only stdlib assertions so it can be run directly with
``python tests/power_monitor/test_jetson_source.py`` in CI environments
that do not have pytest installed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from power_monitor import JetsonPowerSource  # noqa: E402


def test_jetson_power_source_unavailable_without_backend() -> None:
    src = JetsonPowerSource()
    assert not src.is_available()


def test_jetson_power_source_read_once_returns_not_supported() -> None:
    src = JetsonPowerSource()
    reading = src.read_once(timeout_ms=100)
    assert reading.source_name == "jetson"
    assert reading.status == "not_supported"
    assert reading.power_watt is None
    assert reading.quality == "unavailable"


if __name__ == "__main__":
    test_jetson_power_source_unavailable_without_backend()
    test_jetson_power_source_read_once_returns_not_supported()
    print("OK")
