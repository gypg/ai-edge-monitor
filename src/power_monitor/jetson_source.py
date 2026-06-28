"""NVIDIA Jetson / Tegra power source via jtop and tegrastats.

Reads board-level power on Jetson devices where `SysfsPowerSource` does not
have access to the correct rails.  jtop exposes a total power estimate; if
jtop is unavailable, tegrastats single-shot output is used as a fallback.
"""

from __future__ import annotations

import subprocess
import time
from typing import Optional

from .source import PowerReading, PowerSource, ReadStatus


class JetsonPowerSource(PowerSource):
    """Power source for NVIDIA Jetson devices."""

    name = "jetson"

    def __init__(self) -> None:
        self._jtop: Optional[object] = None
        self._jtop_ok = False
        self._tegrastats_ok = False
        self._last_error: Optional[str] = None
        self._probe()

    def _probe(self) -> None:
        try:
            from jtop import jtop

            self._jtop = jtop()
            self._jtop_ok = True
        except Exception as exc:  # pragma: no cover - jtop may not be installed
            self._last_error = f"jtop unavailable: {exc}"
            self._jtop_ok = False

        try:
            result = subprocess.run(
                ["tegrastats", "--stop"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            self._tegrastats_ok = result.returncode in (0, 1)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            self._tegrastats_ok = False

    def is_available(self) -> bool:
        return self._jtop_ok or self._tegrastats_ok

    def read_once(self, timeout_ms: int) -> PowerReading:
        started = time.perf_counter()
        ts_ms = int(time.time() * 1000)

        if not self.is_available():
            return PowerReading(
                ts_ms=ts_ms,
                power_watt=None,
                voltage_v=None,
                current_a=None,
                source_name=self.name,
                quality="unavailable",
                status="not_supported",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error_message=self._last_error or "jetson power source unavailable",
            )

        try:
            power_w, voltage_v, current_a = self._read_power()
        except Exception as exc:  # pragma: no cover - depends on real hardware
            return PowerReading(
                ts_ms=ts_ms,
                power_watt=None,
                voltage_v=None,
                current_a=None,
                source_name=self.name,
                quality="unavailable",
                status="io_error",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error_message=str(exc),
            )

        return PowerReading(
            ts_ms=ts_ms,
            power_watt=power_w,
            voltage_v=voltage_v,
            current_a=current_a,
            source_name=self.name,
            quality="raw",
            status="ok",
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _read_power(self) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """Return (power_w, voltage_v, current_a) from jtop or tegrastats."""
        if self._jtop_ok:
            from jtop import jtop

            with jtop() as jetson:
                power = jetson.power
                if power and isinstance(power, dict):
                    total_mw = power.get("tot")
                    if total_mw is None and "POM_5V_GPU" in power:
                        total_mw = float(power["POM_5V_GPU"])
                    if total_mw is not None:
                        return float(total_mw) / 1000.0, None, None
                raise RuntimeError("jtop did not expose power data")

        if self._tegrastats_ok:
            result = subprocess.run(
                ["tegrastats", "--interval", "100", "--samples", "1"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "tegrastats failed")

            for token in result.stdout.strip().split():
                if token.startswith("VDD_IN"):
                    raw = token.replace("VDD_IN", "").replace("mW", "").split("/")[0]
                    try:
                        power_w = float(raw) / 1000.0
                        return power_w, None, None
                    except ValueError as exc:
                        raise RuntimeError(f"cannot parse tegrastats VDD_IN: {token}") from exc

            raise RuntimeError("tegrastats did not expose VDD_IN")

        raise RuntimeError("no jetson power backend available")
