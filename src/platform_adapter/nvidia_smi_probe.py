from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Literal, Optional, Sequence

from .probe import PlatformCaps, PlatformProbe, RawMetrics

Runner = Callable[[Sequence[str], float], subprocess.CompletedProcess]


@dataclass
class NvidiaSmiMetrics:
    gpu_percent: float
    gpu_mem_used_mb: float
    gpu_mem_total_mb: float
    temperature_c: float


class NvidiaSmiProbe(PlatformProbe):
    name = "nvidia-smi"

    def __init__(self, runner: Optional[Runner] = None, timeout_sec: float = 2.0) -> None:
        self._runner = _run_command if runner is None else runner
        self._timeout_sec = timeout_sec
        self._last_error = ""

    def is_available(self) -> bool:
        try:
            parsed = self._query()
        except Exception as exc:
            self._last_error = f"nvidia-smi unavailable: {exc}"
            return False
        return parsed.gpu_percent >= 0.0

    def detect_caps(self) -> PlatformCaps:
        if self.is_available():
            return PlatformCaps(
                has_cpu=True,
                has_mem=True,
                has_gpu=True,
                has_temp_sensor=True,
                has_power_sensor=False,
                platform_name=self.name,
            )
        return PlatformCaps(
            has_cpu=False,
            has_mem=False,
            has_gpu=False,
            has_temp_sensor=False,
            has_power_sensor=False,
            platform_name=self.name,
            notes={"error": self._last_error or "nvidia-smi unavailable"},
        )

    def read_metrics(self) -> RawMetrics:
        started = time.perf_counter()
        ts_ms = int(time.time() * 1000)
        try:
            parsed = self._query()
        except ValueError as exc:
            return _error_metrics(ts_ms, started, "parse_error", str(exc))
        except Exception as exc:
            return _error_metrics(ts_ms, started, "not_supported", str(exc))
        return RawMetrics(
            ts_ms=ts_ms,
            cpu_percent=0.0,
            mem_used_mb=parsed.gpu_mem_used_mb,
            mem_total_mb=parsed.gpu_mem_total_mb,
            gpu_percent=parsed.gpu_percent,
            gpu_mem_used_mb=parsed.gpu_mem_used_mb,
            temperature_c=parsed.temperature_c,
            probe_name=self.name,
            status="ok",
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _query(self) -> NvidiaSmiMetrics:
        command = [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
        proc = self._runner(command, self._timeout_sec)
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            raise RuntimeError(stderr or f"nvidia-smi exited {proc.returncode}")
        return parse_nvidia_smi_csv(proc.stdout)


def parse_nvidia_smi_csv(output: str) -> NvidiaSmiMetrics:
    first_line = ""
    for line in output.splitlines():
        if line.strip():
            first_line = line.strip()
            break
    fields = [part.strip() for part in first_line.split(",") if part.strip()]
    if len(fields) != 4:
        raise ValueError(f"expected 4 CSV fields from nvidia-smi, got {len(fields)}")
    try:
        values = [float(field) for field in fields]
    except ValueError as exc:
        raise ValueError(f"nvidia-smi output contains a non-numeric field: {first_line!r}") from exc
    return NvidiaSmiMetrics(
        gpu_percent=values[0],
        gpu_mem_used_mb=values[1],
        gpu_mem_total_mb=values[2],
        temperature_c=values[3],
    )


def _run_command(command: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(command),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _error_metrics(
    ts_ms: int,
    started: float,
    status: Literal["parse_error", "not_supported"],
    message: str,
) -> RawMetrics:
    return RawMetrics(
        ts_ms=ts_ms,
        cpu_percent=0.0,
        mem_used_mb=0.0,
        mem_total_mb=0.0,
        gpu_percent=None,
        gpu_mem_used_mb=None,
        temperature_c=None,
        probe_name="nvidia-smi",
        status=status,
        latency_ms=(time.perf_counter() - started) * 1000.0,
        error_message=message,
    )
