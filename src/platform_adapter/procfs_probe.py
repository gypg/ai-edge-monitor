"""Linux /proc-based platform probe (stdlib only).

Reads CPU utilization from /proc/stat (delta between successive calls),
memory from /proc/meminfo, and temperature from
/sys/class/thermal/thermal_zone*/temp. Designed to work without psutil
on generic Linux edge devices (Raspberry Pi, x86 edge servers).

GPU metrics are platform-specific; this probe leaves them as None and
delegates to a future JetsonProbe / NvidiaProbe.
"""

from __future__ import annotations

import os
import time
from typing import Optional, Tuple

from .probe import PlatformCaps, PlatformProbe, RawMetrics


class ProcfsProbe(PlatformProbe):
    name = "procfs"

    STAT_PATH = "/proc/stat"
    MEMINFO_PATH = "/proc/meminfo"
    THERMAL_DIR = "/sys/class/thermal"

    def __init__(self) -> None:
        self._prev_cpu: Optional[Tuple[int, int]] = None  # (idle, total)
        self._thermal_path: Optional[str] = self._discover_thermal()

    def _discover_thermal(self) -> Optional[str]:
        if not os.path.isdir(self.THERMAL_DIR):
            return None
        try:
            for entry in sorted(os.listdir(self.THERMAL_DIR)):
                p = os.path.join(self.THERMAL_DIR, entry, "temp")
                if os.path.isfile(p):
                    return p
        except OSError:
            return None
        return None

    def is_available(self) -> bool:
        return os.path.isfile(self.STAT_PATH) and os.path.isfile(self.MEMINFO_PATH)

    def detect_caps(self) -> PlatformCaps:
        return PlatformCaps(
            has_cpu=os.path.isfile(self.STAT_PATH),
            has_mem=os.path.isfile(self.MEMINFO_PATH),
            has_gpu=False,  # TODO: Jetson/Nvidia/Mali probe integration.
            has_temp_sensor=self._thermal_path is not None,
            has_power_sensor=os.path.isdir("/sys/class/power_supply"),
            platform_name="linux-procfs",
        )

    @staticmethod
    def _read_cpu_idle_total(stat_path: str) -> Tuple[int, int]:
        with open(stat_path, "r", encoding="ascii") as fh:
            line = fh.readline()
        # cpu  user nice system idle iowait irq softirq steal guest guest_nice
        parts = line.split()
        if not parts or parts[0] != "cpu":
            raise ValueError(f"unexpected /proc/stat header: {line!r}")
        nums = [int(x) for x in parts[1:]]
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)  # idle + iowait
        total = sum(nums)
        return idle, total

    @staticmethod
    def _read_meminfo(meminfo_path: str) -> Tuple[float, float]:
        total_kb = avail_kb = None
        with open(meminfo_path, "r", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
                if total_kb is not None and avail_kb is not None:
                    break
        if total_kb is None:
            raise ValueError("MemTotal not found in /proc/meminfo")
        if avail_kb is None:
            avail_kb = 0
        used_mb = max(0.0, (total_kb - avail_kb) / 1024.0)
        total_mb = total_kb / 1024.0
        return used_mb, total_mb

    def _read_temp(self) -> Optional[float]:
        if not self._thermal_path:
            return None
        try:
            with open(self._thermal_path, "r", encoding="ascii") as fh:
                raw = int(fh.read().strip())
            return raw / 1000.0
        except (OSError, ValueError):
            return None

    def read_metrics(self) -> RawMetrics:
        started = time.perf_counter()
        ts_ms = int(time.time() * 1000)

        if not self.is_available():
            return RawMetrics(
                ts_ms=ts_ms, cpu_percent=0.0, mem_used_mb=0.0, mem_total_mb=0.0,
                gpu_percent=None, gpu_mem_used_mb=None, temperature_c=None,
                probe_name=self.name, status="not_supported",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error_message="/proc not available",
            )

        cpu_pct = 0.0
        partial_reason: Optional[str] = None
        try:
            idle, total = self._read_cpu_idle_total(self.STAT_PATH)
            if self._prev_cpu is not None:
                d_idle = idle - self._prev_cpu[0]
                d_total = total - self._prev_cpu[1]
                if d_total > 0:
                    cpu_pct = max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0))
            self._prev_cpu = (idle, total)
        except (OSError, ValueError) as exc:
            partial_reason = f"cpu read failed: {exc}"

        try:
            used_mb, total_mb = self._read_meminfo(self.MEMINFO_PATH)
        except (OSError, ValueError) as exc:
            used_mb, total_mb = 0.0, 0.0
            prefix = partial_reason + "; " if partial_reason else ""
            partial_reason = prefix + f"mem read failed: {exc}"

        temp_c = self._read_temp()
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
