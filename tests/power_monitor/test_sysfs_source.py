"""Tests for SysfsPowerSource device name selection."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from src.power_monitor.source import SysfsPowerSource


def test_sysfs_power_source_prefers_named_device() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        # Create two power supply entries
        bat_dir = Path(tmp) / "BAT0"
        bat_dir.mkdir()
        (bat_dir / "power_now").write_text("5000000\n", encoding="ascii")

        ac_dir = Path(tmp) / "AC"
        ac_dir.mkdir()
        (ac_dir / "power_now").write_text("0\n", encoding="ascii")

        source = SysfsPowerSource(base_dir=tmp, device_name="BAT0")
        assert source.is_available()
        assert source._chosen_path == str(bat_dir)


def test_sysfs_power_source_falls_back_when_device_name_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ac_dir = Path(tmp) / "AC"
        ac_dir.mkdir()
        (ac_dir / "power_now").write_text("0\n", encoding="ascii")

        source = SysfsPowerSource(base_dir=tmp, device_name="UNKNOWN")
        assert source.is_available()
        assert source._chosen_path == str(ac_dir)
