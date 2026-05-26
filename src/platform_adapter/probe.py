"""Probe contract and shared dataclasses for platform_adapter.

This module defines:
- `PlatformCaps`: capability discovery output (what the host can provide).
- `RawMetrics`: the standardized cross-probe reading. Note: per the v2
  module split, `power_watt` is *not* a member of `RawMetrics` — power
  belongs to `power_monitor` and arrives at `aggregator_analyzer` via a
  separate `PowerStatsFrame` channel.
- `PlatformProbe`: abstract base class. Concrete probes implement
  `is_available()`, `detect_caps()`, and `read_metrics()`.
- `DummyProbe`: deterministic-ish synthetic probe used for tests and for
  development hosts that cannot provide real metrics (e.g. Windows).
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Literal, Optional, Protocol

ReadStatus = Literal["ok", "io_error", "parse_error", "not_supported", "partial"]


@dataclass
class PlatformCaps:
    """Capability summary for the current host."""

    has_cpu: bool = True
    has_mem: bool = True
    has_gpu: bool = False
    has_temp_sensor: bool = False
    # Informational only; power collection is owned by power_monitor.
    has_power_sensor: bool = False
    platform_name: str = "unknown"
    notes: Dict[str, str] = field(default_factory=dict)


@dataclass
class RawMetrics:
    """Standardized raw metrics, one snapshot from a probe.

    Fields:
        ts_ms: epoch timestamp (ms)
        cpu_percent: 0..100 system CPU utilization since previous read
        mem_used_mb / mem_total_mb: physical memory in MB
        gpu_percent / gpu_mem_used_mb: optional GPU utilization
        temperature_c: optional system/CPU temperature (max sensor)
        probe_name: probe that produced this reading
        status: read status (ok / partial / error variants)
        latency_ms: wall-clock cost of read_metrics() itself
        error_message: optional details for non-ok status
    """

    ts_ms: int
    cpu_percent: float
    mem_used_mb: float
    mem_total_mb: float
    gpu_percent: Optional[float]
    gpu_mem_used_mb: Optional[float]
    temperature_c: Optional[float]
    probe_name: str
    status: ReadStatus
    latency_ms: float
    error_message: Optional[str] = None


class PlatformProbe(ABC):
    """Abstract platform probe.

    Implementations must:
    - Never raise from `read_metrics` for transient IO/parse errors;
      instead return `status != "ok"` and set `error_message`.
    - Be cheap enough that a single `read_metrics()` finishes well under
      5ms on the target hardware (PRD §3 non-functional requirement).
    """

    name: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool:
        """Return True when this probe can produce readings on the host."""

    @abstractmethod
    def detect_caps(self) -> PlatformCaps:
        """Detect host capabilities (called once at startup)."""

    @abstractmethod
    def read_metrics(self) -> RawMetrics:
        """Read one snapshot."""

    def close(self) -> None:
        """Release resources (default no-op)."""


class _ScenarioLike(Protocol):
    def sample(self) -> object: ...


class CompositeProbe(PlatformProbe):
    """Chain multiple probes together, merging their readings.

    The first probe supplies CPU / memory / temperature; any subsequent
    probes fill in fields that the primary left as None (e.g. GPU metrics
    from NvidiaSmiProbe).  ``detect_caps`` merges all capabilities.
    """

    def __init__(self, probes: list) -> None:
        if not probes:
            raise ValueError("CompositeProbe requires at least one probe")
        self._probes = list(probes)
        self.name = "+".join(p.name for p in self._probes)

    def is_available(self) -> bool:
        return any(p.is_available() for p in self._probes)

    def detect_caps(self) -> PlatformCaps:
        caps = PlatformCaps(platform_name=self.name)
        for p in self._probes:
            if not p.is_available():
                continue
            c = p.detect_caps()
            caps.has_cpu = caps.has_cpu or c.has_cpu
            caps.has_mem = caps.has_mem or c.has_mem
            caps.has_gpu = caps.has_gpu or c.has_gpu
            caps.has_temp_sensor = caps.has_temp_sensor or c.has_temp_sensor
            caps.has_power_sensor = caps.has_power_sensor or c.has_power_sensor
        return caps

    def read_metrics(self) -> RawMetrics:
        merged: RawMetrics | None = None
        total_latency = 0.0
        errors: list[str] = []
        for p in self._probes:
            reading = p.read_metrics()
            total_latency += reading.latency_ms
            if merged is None:
                merged = reading
            else:
                merged = _merge_metrics(merged, reading)
            if reading.error_message:
                errors.append(reading.error_message)
        assert merged is not None
        if errors:
            merged = RawMetrics(
                ts_ms=merged.ts_ms,
                cpu_percent=merged.cpu_percent,
                mem_used_mb=merged.mem_used_mb,
                mem_total_mb=merged.mem_total_mb,
                gpu_percent=merged.gpu_percent,
                gpu_mem_used_mb=merged.gpu_mem_used_mb,
                temperature_c=merged.temperature_c,
                probe_name=self.name,
                status="partial",
                latency_ms=total_latency,
                error_message="; ".join(errors),
            )
        else:
            merged = RawMetrics(
                ts_ms=merged.ts_ms,
                cpu_percent=merged.cpu_percent,
                mem_used_mb=merged.mem_used_mb,
                mem_total_mb=merged.mem_total_mb,
                gpu_percent=merged.gpu_percent,
                gpu_mem_used_mb=merged.gpu_mem_used_mb,
                temperature_c=merged.temperature_c,
                probe_name=self.name,
                status="ok",
                latency_ms=total_latency,
            )
        return merged


def _merge_metrics(base: RawMetrics, extra: RawMetrics) -> RawMetrics:
    """Fill None / 0.0 fields in *base* with values from *extra*."""
    return RawMetrics(
        ts_ms=base.ts_ms,
        cpu_percent=base.cpu_percent if base.cpu_percent else extra.cpu_percent,
        mem_used_mb=base.mem_used_mb if base.mem_used_mb else extra.mem_used_mb,
        mem_total_mb=base.mem_total_mb if base.mem_total_mb else extra.mem_total_mb,
        gpu_percent=base.gpu_percent if base.gpu_percent is not None else extra.gpu_percent,
        gpu_mem_used_mb=(
            base.gpu_mem_used_mb if base.gpu_mem_used_mb is not None else extra.gpu_mem_used_mb
        ),
        temperature_c=(
            base.temperature_c if base.temperature_c is not None else extra.temperature_c
        ),
        probe_name=base.probe_name,
        status=base.status,
        latency_ms=base.latency_ms,
        error_message=base.error_message,
    )


class DummyProbe(PlatformProbe):
    """Synthetic probe used for tests and development hosts.

    Default mode produces stable readings with optional jitter so
    baseline overhead measurements aren't dominated by entropy.

    When `scenario` is provided (any object with a `.sample()` method
    returning an object with `cpu_percent`, `mem_used_mb`, `temperature_c`,
    `power_watt` attributes), readings follow the scenario's load shape
    instead. The scenario's `power_watt` is intentionally ignored here —
    power belongs to `power_monitor`. Pair this with a
    scenario-aware DummySource to drive both axes.
    """

    name = "dummy"

    def __init__(
        self,
        base_cpu: float = 12.0,
        jitter: float = 2.0,
        scenario: Optional[_ScenarioLike] = None,
    ) -> None:
        self.base_cpu = base_cpu
        self.jitter = jitter
        self.scenario = scenario

    def is_available(self) -> bool:
        return True

    def detect_caps(self) -> PlatformCaps:
        has_temp = self.scenario is not None
        return PlatformCaps(
            has_cpu=True,
            has_mem=True,
            has_gpu=False,
            has_temp_sensor=has_temp,
            has_power_sensor=False,
            platform_name="dummy",
        )

    def read_metrics(self) -> RawMetrics:
        started = time.perf_counter()
        ts_ms = int(time.time() * 1000)
        if self.scenario is not None:
            point = self.scenario.sample()
            if not hasattr(point, "cpu_percent") or not hasattr(point, "mem_used_mb"):
                raise TypeError("scenario.sample() must expose cpu_percent/mem_used_mb")
            cpu = float(getattr(point, "cpu_percent"))
            mem_used = float(getattr(point, "mem_used_mb"))
            temperature = getattr(point, "temperature_c", None)
            temp = None if temperature is None else float(temperature)
        else:
            cpu = max(0.0, min(100.0, self.base_cpu + random.uniform(-self.jitter, self.jitter)))
            mem_used = 512.0
            temp = None
        latency_ms = (time.perf_counter() - started) * 1000.0
        return RawMetrics(
            ts_ms=ts_ms,
            cpu_percent=cpu,
            mem_used_mb=mem_used,
            mem_total_mb=4096.0,
            gpu_percent=None,
            gpu_mem_used_mb=None,
            temperature_c=temp,
            probe_name=self.name,
            status="ok",
            latency_ms=latency_ms,
        )
