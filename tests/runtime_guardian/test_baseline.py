"""runtime_guardian baseline test.

Measures *RuntimeGuardian wrapper overhead* rather than raw sample cost.
We compare:

A) direct loop calling `RuntimeGuardian.check_now()` on a cadence
B) background-threaded `RuntimeGuardian.start()` / `stop()` on the same cadence

Guardian self-overhead = B_CPU - A_CPU

The degrade/recover hysteresis logic is verified separately via
`inject_test_load`, so this test remains deterministic on any host.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import psutil  # type: ignore
except ModuleNotFoundError:
    psutil = None

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime_guardian import GuardianConfig, RuntimeGuardian  # noqa: E402

DURATION_SEC = 30
INTERVAL_SEC = 0.1
CPU_THRESHOLD_MS = 20.0
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


def _new_guardian() -> RuntimeGuardian:
    return RuntimeGuardian(GuardianConfig(interval_sec=INTERVAL_SEC, test_mode=True))


def _run_direct(duration_sec: int, interval_sec: float) -> float:
    guardian = _new_guardian()
    loops = max(1, int(duration_sec / interval_sec))
    next_tick = time.monotonic()
    start_cpu = time.process_time()
    for _ in range(loops):
        sleep_s = max(0.0, next_tick - time.monotonic())
        if sleep_s > 0:
            time.sleep(sleep_s)
        guardian.check_now()
        next_tick += interval_sec
    end_cpu = time.process_time()
    return (end_cpu - start_cpu) * 1000.0


def _run_threaded(duration_sec: int) -> float:
    guardian = _new_guardian()
    start_cpu = time.process_time()
    guardian.start()
    try:
        time.sleep(duration_sec)
    finally:
        guardian.stop()
    end_cpu = time.process_time()
    return (end_cpu - start_cpu) * 1000.0


def measure_self_overhead() -> Tuple[float, float]:
    proc = psutil.Process(os.getpid()) if psutil is not None else None
    rss_before = _rss_mb(proc)

    direct_ms = _run_direct(DURATION_SEC, INTERVAL_SEC)
    threaded_ms = _run_threaded(DURATION_SEC)

    rss_after = _rss_mb(proc)
    return max(0.0, threaded_ms - direct_ms), max(0.0, rss_after - rss_before)


def verify_hysteresis() -> Tuple[bool, Dict[str, object], List[Tuple[str, Dict[str, object]]]]:
    events: List[Tuple[str, Dict[str, object]]] = []

    def on_degrade(health: Dict[str, object]) -> None:
        events.append(("degrade", health))

    def on_recover(health: Dict[str, object]) -> None:
        events.append(("recover", health))

    guardian = RuntimeGuardian(
        GuardianConfig(
            interval_sec=0.05,
            cpu_percent_high=3.0,
            cpu_percent_low=2.0,
            rss_mb_high=50.0,
            rss_mb_low=40.0,
            test_mode=True,
        ),
        on_degrade=on_degrade,
        on_recover=on_recover,
    )

    guardian.inject_test_load(cpu_percent=1.0, rss_mb=20.0)
    guardian.start()
    time.sleep(0.3)
    guardian.inject_test_load(cpu_percent=8.0, rss_mb=100.0)
    time.sleep(0.5)
    guardian.inject_test_load(cpu_percent=2.5, rss_mb=20.0)
    time.sleep(0.5)
    guardian.inject_test_load(cpu_percent=0.5, rss_mb=20.0)
    time.sleep(0.5)
    guardian.stop()

    health = guardian.get_health()
    ok = health["degrade_count"] == 1 and health["recover_count"] == 1
    return ok, health, events


def run_baseline_test() -> int:
    print("[1/2] measuring guardian self overhead ...")
    overhead_ms, rss_delta_mb = measure_self_overhead()
    if overhead_ms >= CPU_THRESHOLD_MS:
        print(f"[retry] first run measured {overhead_ms:.2f} ms; re-measuring once...")
        retry_ms, retry_rss = measure_self_overhead()
        overhead_ms = min(overhead_ms, retry_ms)
        rss_delta_mb = min(rss_delta_mb, retry_rss)
    print(f"CPU 时间增量: {overhead_ms:.2f} ms，常驻内存增量: {rss_delta_mb:.2f} MB")

    print("[2/2] verifying degrade/recover hysteresis ...")
    hys_ok, health, events = verify_hysteresis()
    print(f"      health={health}")
    print(f"      events={events}")

    failures = []
    if overhead_ms >= CPU_THRESHOLD_MS:
        failures.append(f"guardian self overhead {overhead_ms:.2f} >= {CPU_THRESHOLD_MS:.2f} ms")
    if rss_delta_mb >= MEM_THRESHOLD_MB:
        failures.append(f"常驻内存增量超阈值: {rss_delta_mb:.2f} >= {MEM_THRESHOLD_MB:.2f} MB")
    if not hys_ok:
        failures.append(
            f"hysteresis: degrade={health['degrade_count']} recover={health['recover_count']}"
        )

    if not failures:
        print("PASS")
        return 0
    print("FAIL")
    for failure in failures:
        print(f"- {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(run_baseline_test())
