"""Power source abstractions for power_monitor.

This module defines the source contract, a DummySource for tests, and a
SysfsPowerSource that reads from /sys/class/power_supply on Linux edge
devices (the PRD's first-priority backend).

Notes:
- TODO: add JetsonStatsPowerSource (jtop) and TegrastatsPowerSource for
  Jetson-specific power rails behind this abstraction.
"""

from __future__ import annotations

import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Literal, Optional, Protocol, Tuple

Quality = Literal["raw", "derived", "estimated", "unavailable"]
ReadStatus = Literal["ok", "timeout", "io_error", "parse_error", "not_supported"]


@dataclass
class PowerReading:
    """A single power reading.

    Attributes:
        ts_ms: Epoch timestamp in milliseconds.
        power_watt: Power in watts, or None when unavailable.
        voltage_v: Voltage in volts, if available.
        current_a: Current in amps, if available.
        source_name: Logical source identifier.
        quality: Data quality level.
        status: Read status code.
        latency_ms: Source read latency in milliseconds.
        error_message: Optional error detail for non-ok status.
    """

    ts_ms: int
    power_watt: Optional[float]
    voltage_v: Optional[float]
    current_a: Optional[float]
    source_name: str
    quality: Quality
    status: ReadStatus
    latency_ms: float
    error_message: Optional[str] = None


class PowerSource(ABC):
    """Abstract power source contract."""

    name: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool:
        """Return True when this source can be used on current host."""

    @abstractmethod
    def read_once(self, timeout_ms: int) -> PowerReading:
        """Read one sample.

        Implementations should return non-ok status instead of raising for
        transient read failures.
        """

    def close(self) -> None:
        """Release source resources (default no-op)."""


class _ScenarioLike(Protocol):
    def sample(self) -> object:
        ...


class DummySource(PowerSource):
    """Deterministic-ish fake source for tests and benchmarks.

    Default mode produces synthetic readings around `base_watt` with
    `jitter_watt` noise. When `scenario` is given (any object with a
    `.sample()` method that returns an object exposing `power_watt`),
    readings follow the scenario shape instead — the scenario's CPU /
    memory / temperature attributes are ignored here (those are read by
    DummyProbe on the platform side).
    """

    name = "dummy"

    def __init__(
        self,
        base_watt: float = 8.0,
        jitter_watt: float = 1.0,
        fail_rate: float = 0.0,
        scenario: Optional[_ScenarioLike] = None,
    ) -> None:
        self.base_watt = base_watt
        self.jitter_watt = jitter_watt
        self.fail_rate = fail_rate
        self.scenario = scenario

    def is_available(self) -> bool:
        return True

    def read_once(self, timeout_ms: int) -> PowerReading:
        started = time.perf_counter()
        if random.random() < self.fail_rate:
            latency_ms = (time.perf_counter() - started) * 1000.0
            return PowerReading(
                ts_ms=int(time.time() * 1000),
                power_watt=None,
                voltage_v=None,
                current_a=None,
                source_name=self.name,
                quality="unavailable",
                status="timeout",
                latency_ms=latency_ms,
                error_message="dummy timeout",
            )

        if self.scenario is not None:
            point = self.scenario.sample()
            if not hasattr(point, "power_watt"):
                raise TypeError("scenario.sample() must expose power_watt")
            power = max(0.1, float(getattr(point, "power_watt")))
        else:
            power = max(0.1, self.base_watt + random.uniform(-self.jitter_watt, self.jitter_watt))
        voltage = 5.0
        current = power / voltage
        latency_ms = (time.perf_counter() - started) * 1000.0
        return PowerReading(
            ts_ms=int(time.time() * 1000),
            power_watt=power,
            voltage_v=voltage,
            current_a=current,
            source_name=self.name,
            quality="raw",
            status="ok",
            latency_ms=latency_ms,
        )


class SysfsPowerSource(PowerSource):
    """Read board-level power from `/sys/class/power_supply/*`.

    This is the PRD's first-priority backend for generic Linux edge devices.
    Strategy:
        1. Scan `/sys/class/power_supply/` for a battery/mains entry that
           exposes either `power_now` (preferred, microwatts) or both
           `current_now` (microamps) and `voltage_now` (microvolts).
        2. Convert to W/V/A with `quality="raw"` for direct power_now,
           `quality="derived"` when computing P = V * I.
        3. Never raise for IO/parse errors; return non-ok status instead.

    Notes:
        - psutil intentionally NOT used here for the actual power read:
          psutil does not expose board-level power on most Linux devices.
          Per the PRD, we read sysfs directly to avoid extra overhead.
        - On hosts without `/sys/class/power_supply` (Windows, macOS, or
          Linux without a battery driver), `is_available()` returns False
          and `read_once()` returns `status="not_supported"`.
        - TODO: extend selection to honor a configured device name.
    """

    name = "sysfs"
    BASE_DIR = "/sys/class/power_supply"

    def __init__(self, base_dir: Optional[str] = None) -> None:
        self.base_dir = base_dir or self.BASE_DIR
        self._chosen_path: Optional[str] = None
        self._mode: Optional[Literal["power_now", "iv"]] = None
        self._probe()

    def _probe(self) -> None:
        if not os.path.isdir(self.base_dir):
            return
        try:
            entries = sorted(os.listdir(self.base_dir))
        except OSError:
            return
        for entry in entries:
            path = os.path.join(self.base_dir, entry)
            if os.path.isfile(os.path.join(path, "power_now")):
                self._chosen_path = path
                self._mode = "power_now"
                return
            if os.path.isfile(os.path.join(path, "current_now")) and os.path.isfile(
                os.path.join(path, "voltage_now")
            ):
                self._chosen_path = path
                self._mode = "iv"
                return

    def is_available(self) -> bool:
        return self._chosen_path is not None and self._mode is not None

    @staticmethod
    def _read_int_file(path: str) -> int:
        with open(path, "r", encoding="ascii") as fh:
            return int(fh.read().strip())

    def read_once(self, timeout_ms: int) -> PowerReading:
        started = time.perf_counter()
        ts_ms = int(time.time() * 1000)

        if not self.is_available():
            latency_ms = (time.perf_counter() - started) * 1000.0
            return PowerReading(
                ts_ms=ts_ms,
                power_watt=None,
                voltage_v=None,
                current_a=None,
                source_name=self.name,
                quality="unavailable",
                status="not_supported",
                latency_ms=latency_ms,
                error_message=f"sysfs base not found or no usable entry under {self.base_dir!r}",
            )

        try:
            assert self._chosen_path is not None
            if self._mode == "power_now":
                p_uw = self._read_int_file(os.path.join(self._chosen_path, "power_now"))
                power_w = p_uw / 1_000_000.0
                voltage_v: Optional[float] = None
                current_a: Optional[float] = None
                quality: Quality = "raw"
                v_path = os.path.join(self._chosen_path, "voltage_now")
                if os.path.isfile(v_path):
                    try:
                        voltage_v = self._read_int_file(v_path) / 1_000_000.0
                    except (OSError, ValueError):
                        voltage_v = None
            else:  # iv
                v_uv = self._read_int_file(os.path.join(self._chosen_path, "voltage_now"))
                i_ua = self._read_int_file(os.path.join(self._chosen_path, "current_now"))
                voltage_v = v_uv / 1_000_000.0
                current_a = i_ua / 1_000_000.0
                power_w = voltage_v * current_a
                quality = "derived"
        except (OSError, ValueError) as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            status: ReadStatus = "io_error" if isinstance(exc, OSError) else "parse_error"
            return PowerReading(
                ts_ms=ts_ms,
                power_watt=None,
                voltage_v=None,
                current_a=None,
                source_name=self.name,
                quality="unavailable",
                status=status,
                latency_ms=latency_ms,
                error_message=f"{type(exc).__name__}: {exc}",
            )

        latency_ms = (time.perf_counter() - started) * 1000.0
        return PowerReading(
            ts_ms=ts_ms,
            power_watt=power_w,
            voltage_v=voltage_v,
            current_a=current_a,
            source_name=self.name,
            quality=quality,
            status="ok",
            latency_ms=latency_ms,
        )


def select_default_source(prefer: Tuple[str, ...] = ("sysfs",)) -> PowerSource:
    """Return the first available source from `prefer`, falling back to DummySource.

    Used by the integration demo to wire a "real if possible, mock otherwise"
    pipeline without the caller hand-rolling probe logic.
    """
    candidates: List[PowerSource] = []
    for name in prefer:
        if name == "sysfs":
            candidates.append(SysfsPowerSource())
        # TODO: add jtop, tegrastats handlers here.
    for src in candidates:
        if src.is_available():
            return src
    return DummySource()
