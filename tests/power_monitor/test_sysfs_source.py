"""Tests for SysfsPowerSource device name selection.

This module uses only stdlib assertions so it can be run directly with
``python tests/power_monitor/test_sysfs_source.py`` in CI environments that
do not have pytest installed.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from power_monitor.source import SysfsPowerSource  # noqa: E402


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


if __name__ == "__main__":
    test_sysfs_power_source_prefers_named_device()
    test_sysfs_power_source_falls_back_when_device_name_missing()
    print("OK")
