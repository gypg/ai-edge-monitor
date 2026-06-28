"""psutil-backed cross-platform probe.

Used as a fallback when /proc isn't available (Windows dev hosts, macOS).
On Linux this overlaps with ProcfsProbe; ProcfsProbe is preferred there
because it avoids the psutil dependency and is faster on cold caches.

GPU metrics on NVIDIA/Jetson platforms are provided by NvidiaSmiProbe
and JetsonProbe; this probe intentionally leaves GPU fields as None so
that a CompositeProbe can fill them in.
"""

from __future__ import annotations

import time
from typing import Optional

from .probe import PlatformCaps, PlatformProbe, RawMetrics

try:  # psutil is optional
    import psutil

    _PSUTIL_OK = True
except ModuleNotFoundError:
    psutil = None
    _PSUTIL_OK = False


class PsutilProbe(PlatformProbe):
    name = "psutil"

    def __init__(self) -> None:
        if _PSUTIL_OK:
            try:
                psutil.cpu_percent(interval=None)
            except Exception:
                pass

    def is_available(self) -> bool:
        return _PSUTIL_OK

    def detect_caps(self) -> PlatformCaps:
        if not _PSUTIL_OK:
            return PlatformCaps(has_cpu=False, has_mem=False, platform_name="psutil-missing")
        has_temp = False
        try:
            sensors = getattr(psutil, "sensors_temperatures", None)
            has_temp = bool(sensors and sensors())
        except Exception:
            has_temp = False
        return PlatformCaps(
            has_cpu=True,
            has_mem=True,
            has_gpu=False,
            has_temp_sensor=has_temp,
            has_power_sensor=False,
            platform_name="psutil",
        )

    def _read_temperature_c(self) -> Optional[float]:
        try:
            sensors = getattr(psutil, "sensors_temperatures", None)
            if not sensors:
                return None
            data = sensors()
            if not data:
                return None
            best: Optional[float] = None
            for entries in data.values():
                for entry in entries:
                    cur = getattr(entry, "current", None)
                    if cur is None:
                        continue
                    if best is None or cur > best:
                        best = float(cur)
            return best
        except Exception:
            return None

    def read_metrics(self) -> RawMetrics:
        started = time.perf_counter()
        ts_ms = int(time.time() * 1000)

        if not _PSUTIL_OK:
            return RawMetrics(
                ts_ms=ts_ms,
                cpu_percent=0.0,
                mem_used_mb=0.0,
                mem_total_mb=0.0,
                gpu_percent=None,
                gpu_mem_used_mb=None,
                temperature_c=None,
                probe_name=self.name,
                status="not_supported",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error_message="psutil not installed",
            )

        partial_reason: Optional[str] = None
        try:
            cpu_pct = float(psutil.cpu_percent(interval=None))
        except Exception as exc:
            cpu_pct = 0.0
            partial_reason = f"cpu_percent failed: {exc}"

        try:
            vm = psutil.virtual_memory()
            used_mb = (vm.total - vm.available) / (1024 * 1024)
            total_mb = vm.total / (1024 * 1024)
        except Exception as exc:
            used_mb, total_mb = 0.0, 0.0
            prefix = partial_reason + "; " if partial_reason else ""
            partial_reason = prefix + f"virtual_memory failed: {exc}"

        temp_c = self._read_temperature_c()
        latency_ms = (time.perf_counter() - started) * 1000.0
        return RawMetrics(
            ts_ms=ts_ms,
            cpu_percent=cpu_pct,
            mem_used_mb=used_mb,
            mem_total_mb=total_mb,
            gpu_percent=None,
            gpu_mem_used_mb=None,
            temperature_c=temp_c,
            probe_name=self.name,
            status="ok" if partial_reason is None else "partial",
            latency_ms=latency_ms,
            error_message=partial_reason,
        )
