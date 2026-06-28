"""Tests for JetsonPowerSource.

Verifies that the Jetson power source correctly reports unavailability when
jtop/tegrastats are absent and that the public contract (is_available,
read_once) behaves like any other PowerSource.
"""

from __future__ import annotations

from src.power_monitor.jetson_source import JetsonPowerSource


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
