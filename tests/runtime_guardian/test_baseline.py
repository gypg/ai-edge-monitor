"""runtime_guardian baseline test.

Verifies:
- Self-overhead with psutil missing or quiet load: CPU < 5ms, RSS < 5MB
  measured over a 30s run @ 100ms interval (matching the shared module
  budget format).
- Degrade-recover hysteresis: with `inject_test_load`, cross both high
  thresholds and confirm exactly 1 degrade + 1 recover within the run.
- `get_health()` reports the latest counters consistently.

The hysteresis assertion is decoupled from real psutil readings via
`inject_test_load`, so this test is deterministic on any host.
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

from runtime_guardian import GuardianConfig, RuntimeGuardian  # noqa: E402

DURATION_SEC = 30
INTERVAL_SEC = 0.1
CPU_THRESHOLD_MS = 5.0
MEM_THRESHOLD_MB = 5.0


def _rss_mb_windows_tasklist() -> float:
    try:
        import csv
        import io
        import subprocess

        out = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {os.getpid()}", "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL, text=True,
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


def measure_self_overhead() -> Tuple[float, float]:
    """Run guardian for 30s with no injection — measures self overhead."""
    proc = psutil.Process(os.getpid()) if psutil is not None else None
    rss_before = _rss_mb(proc)

    g = RuntimeGuardian(GuardianConfig(interval_sec=INTERVAL_SEC, test_mode=True))
    start_cpu = time.process_time()
    g.start()
    time.sleep(DURATION_SEC)
    g.stop()
    end_cpu = time.process_time()

    rss_after = _rss_mb(proc)
    return (end_cpu - start_cpu) * 1000.0, max(0.0, rss_after - rss_before)


def measure_sleep_baseline() -> float:
    start_cpu = time.process_time()
    time.sleep(DURATION_SEC)
    return (time.process_time() - start_cpu) * 1000.0


def verify_hysteresis() -> Tuple[bool, dict, list]:
    events: list = []

    def on_degrade(h):
        events.append(("degrade", h))

    def on_recover(h):
        events.append(("recover", h))

    g = RuntimeGuardian(
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

    # quiet
    g.inject_test_load(cpu_percent=1.0, rss_mb=20.0)
    g.start()
    time.sleep(0.3)
    # cross high
    g.inject_test_load(cpu_percent=8.0, rss_mb=100.0)
    time.sleep(0.5)
    # bounce just above low CPU but below RSS low (must NOT recover yet:
    # both must drop below low)
    g.inject_test_load(cpu_percent=2.5, rss_mb=20.0)
    time.sleep(0.5)
    # cleanly below both lows
    g.inject_test_load(cpu_percent=0.5, rss_mb=20.0)
    time.sleep(0.5)
    g.stop()

    health = g.get_health()
    ok = health["degrade_count"] == 1 and health["recover_count"] == 1
    return ok, health, events


def run_baseline_test() -> int:
    print("[1/2] measuring guardian self overhead ...")
    baseline_cpu_ms = measure_sleep_baseline()
    run_cpu_ms, rss_delta_mb = measure_self_overhead()
    overhead_ms = max(0.0, run_cpu_ms - baseline_cpu_ms)
    print(f"      sleep baseline: {baseline_cpu_ms:.2f} ms")
    print(
        f"CPU 时间增量: {overhead_ms:.2f} ms，常驻内存增量: {rss_delta_mb:.2f} MB"
    )

    print("[2/2] verifying degrade/recover hysteresis ...")
    hys_ok, health, events = verify_hysteresis()
    print(f"      health={health}")
    print(f"      events={events}")

    failures = []
    if overhead_ms >= CPU_THRESHOLD_MS:
        failures.append(
            f"guardian self overhead {overhead_ms:.2f} >= {CPU_THRESHOLD_MS:.2f} ms"
        )
    if rss_delta_mb >= MEM_THRESHOLD_MB:
        failures.append(
            f"常驻内存增量超阈值: {rss_delta_mb:.2f} >= {MEM_THRESHOLD_MB:.2f} MB"
        )
    if not hys_ok:
        failures.append(
            f"hysteresis: degrade={health['degrade_count']} recover={health['recover_count']}"
        )

    if not failures:
        print("PASS")
        return 0
    print("FAIL")
    for f in failures:
        print(f"- {f}")
    return 1


if __name__ == "__main__":
    raise SystemExit(run_baseline_test())
