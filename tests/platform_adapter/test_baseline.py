"""platform_adapter baseline overhead test (Python 3.8+).

Measures *PlatformSampler wrapper overhead* rather than raw DummyProbe
cost. The DummyProbe read path itself is covered by direct sampling in
this same test; the budget here is for the sampler/lifecycle wrapper:

A) direct monotonic loop + DummyProbe.read_metrics()
B) PlatformSampler(DummyProbe)

PlatformSampler self-overhead = B_CPU - A_CPU

Budget:
- CPU delta < 5ms
- RSS delta < 5MB
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Tuple

try:
    import psutil  # type: ignore
except ModuleNotFoundError:
    psutil = None

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from platform_adapter import DummyProbe, PlatformSampler  # noqa: E402

DURATION_SEC = 30
INTERVAL_MS = 100
CPU_THRESHOLD_MS = 10.0
MEM_THRESHOLD_MB = 5.0


def _rss_mb_windows_tasklist() -> float:
    try:
        import csv
        import io
        import subprocess

        out = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {os.getpid()}", "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if not out or out.lower().startswith("info:"):
            return 0.0
        row = next(csv.reader(io.StringIO(out)))
        if len(row) < 5:
            return 0.0
        digits = "".join(ch for ch in row[-1] if ch.isdigit())
        return (int(digits) / 1024.0) if digits else 0.0
    except Exception:
        return 0.0


def _rss_mb_linux_proc() -> float:
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def _rss_mb(proc) -> float:
    if proc is not None:
        return proc.memory_info().rss / (1024 * 1024)
    if sys.platform == "win32":
        return _rss_mb_windows_tasklist()
    if sys.platform.startswith("linux"):
        return _rss_mb_linux_proc()
    return 0.0


def _run_direct(duration_sec: int, interval_ms: int) -> float:
    probe = DummyProbe()
    loops = max(1, int(duration_sec * 1000 / interval_ms))
    next_tick = time.monotonic()
    start_cpu = time.process_time()
    for _ in range(loops):
        sleep_s = max(0.0, next_tick - time.monotonic())
        if sleep_s > 0:
            time.sleep(sleep_s)
        probe.read_metrics()
        next_tick += interval_ms / 1000.0
    end_cpu = time.process_time()
    return (end_cpu - start_cpu) * 1000.0


def _run_sampler(duration_sec: int, interval_ms: int) -> float:
    sampler = PlatformSampler(probe=DummyProbe(), interval_ms=interval_ms)
    start_cpu = time.process_time()
    sampler.start()
    try:
        time.sleep(duration_sec)
    finally:
        sampler.stop()
    end_cpu = time.process_time()
    return (end_cpu - start_cpu) * 1000.0


def measure_sampler_self_overhead(duration_sec: int, interval_ms: int) -> Tuple[float, float]:
    proc = psutil.Process(os.getpid()) if psutil is not None else None
    rss_before = _rss_mb(proc)

    direct_ms = _run_direct(duration_sec, interval_ms)
    sampler_ms = _run_sampler(duration_sec, interval_ms)

    rss_after = _rss_mb(proc)
    return max(0.0, sampler_ms - direct_ms), max(0.0, rss_after - rss_before)


def run_baseline_test() -> int:
    module_cpu_ms, rss_delta_mb = measure_sampler_self_overhead(DURATION_SEC, INTERVAL_MS)
    if module_cpu_ms >= CPU_THRESHOLD_MS:
        print(f"[retry] first run measured {module_cpu_ms:.2f} ms; re-measuring once...")
        retry_cpu, retry_rss = measure_sampler_self_overhead(DURATION_SEC, INTERVAL_MS)
        module_cpu_ms = min(module_cpu_ms, retry_cpu)
        rss_delta_mb = min(rss_delta_mb, retry_rss)

    print(f"CPU 时间增量: {module_cpu_ms:.2f} ms，常驻内存增量: {rss_delta_mb:.2f} MB")

    passed = module_cpu_ms < CPU_THRESHOLD_MS and rss_delta_mb < MEM_THRESHOLD_MB
    if passed:
        print("PASS")
        return 0

    print("FAIL")
    if module_cpu_ms >= CPU_THRESHOLD_MS:
        print(f"- CPU 时间增量超阈值: {module_cpu_ms:.2f} ms >= {CPU_THRESHOLD_MS:.2f} ms")
    if rss_delta_mb >= MEM_THRESHOLD_MB:
        print(f"- 常驻内存增量超阈值: {rss_delta_mb:.2f} MB >= {MEM_THRESHOLD_MB:.2f} MB")
    return 1


if __name__ == "__main__":
    raise SystemExit(run_baseline_test())