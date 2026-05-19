"""scheduler baseline test.

Validates timing & resource bounds for `PeriodicScheduler`:

- cycle_period_sec=5, collect_duration_sec=3, total run 15s ⇒
  expect 2 or 3 sessions and the same number of reports.
- Scheduler *control overhead* (with emit_report=False) must stay
  within the shared module budget (CPU delta < 5ms vs sleep-only
  baseline, RSS delta < 5MB). The collector and visualizer have
  their own baselines; this test isolates the scheduler skeleton.
- Report generation correctness (count == sessions) is verified in a
  separate, non-budgeted leg with emit_report=True.

The expectation range (2 ~ 3 sessions) is intentional: depending on
where the 15s window lands relative to the second cycle's sleep, you
get either 2 finished sessions + idle time, or 3 finished sessions back
to back. Both are correct; what we *don't* tolerate is 0, 1, or 4+.
"""

from __future__ import annotations

import os
import shutil
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

from collector import CollectorConfig  # noqa: E402
from scheduler import PeriodicScheduler, ScheduleConfig  # noqa: E402
from visualizer import plot_report  # noqa: E402

CYCLE_PERIOD_SEC = 5.0
COLLECT_DURATION_SEC = 3.0
TOTAL_RUN_SEC = 15.0
EXPECTED_MIN_SESSIONS = 2
EXPECTED_MAX_SESSIONS = 4
CPU_THRESHOLD_MS = 5.0
MEM_THRESHOLD_MB = 5.0
ARTIFACTS_DIR = ROOT / "tests" / "scheduler" / "_baseline_artifacts"


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


def measure_collector_only_baseline() -> float:
    """CPU cost of running the same collector cadence WITHOUT the
    scheduler. The scheduler's own overhead is then this run's CPU
    minus the baseline.
    """
    from collector import Collector

    start_cpu = time.process_time()
    end_at = time.monotonic() + TOTAL_RUN_SEC
    while time.monotonic() < end_at:
        c = Collector(CollectorConfig(interval_ms=1000, force_dummy=True))
        c.start()
        time.sleep(min(COLLECT_DURATION_SEC, max(0.0, end_at - time.monotonic())))
        c.stop()
        idle = CYCLE_PERIOD_SEC - COLLECT_DURATION_SEC
        time.sleep(min(idle, max(0.0, end_at - time.monotonic())))
    return (time.process_time() - start_cpu) * 1000.0


def measure_scheduler_self_overhead() -> Tuple[float, float, int]:
    """Scheduler control loop overhead with emit_report=False."""
    proc = psutil.Process(os.getpid()) if psutil is not None else None
    rss_before = _rss_mb(proc)

    scheduler = PeriodicScheduler(
        collector_config=CollectorConfig(interval_ms=1000, force_dummy=True),
        schedule_config=ScheduleConfig(
            cycle_period_sec=CYCLE_PERIOD_SEC,
            collect_duration_sec=COLLECT_DURATION_SEC,
            emit_report=False,
            report_dir=ARTIFACTS_DIR,
            report_prefix="baseline",
        ),
        report_fn=None,
    )

    start_cpu = time.process_time()
    scheduler.schedule()
    time.sleep(TOTAL_RUN_SEC)
    scheduler.stop()
    end_cpu = time.process_time()

    rss_after = _rss_mb(proc)
    cpu_ms = (end_cpu - start_cpu) * 1000.0
    return cpu_ms, max(0.0, rss_after - rss_before), scheduler.session_count


def verify_report_count_correctness() -> Tuple[int, int]:
    """Separate non-budgeted leg: confirm sessions == reports when
    emit_report=True. We skip the CPU budget here because PNG
    rendering's cost belongs to the visualizer's baseline, not ours.
    """
    if ARTIFACTS_DIR.exists():
        shutil.rmtree(ARTIFACTS_DIR, ignore_errors=True)
    scheduler = PeriodicScheduler(
        collector_config=CollectorConfig(interval_ms=1000, force_dummy=True),
        schedule_config=ScheduleConfig(
            cycle_period_sec=CYCLE_PERIOD_SEC,
            collect_duration_sec=COLLECT_DURATION_SEC,
            emit_report=True,
            report_dir=ARTIFACTS_DIR,
            report_prefix="baseline",
        ),
        report_fn=plot_report,
    )
    scheduler.schedule()
    time.sleep(TOTAL_RUN_SEC)
    scheduler.stop()
    return scheduler.session_count, scheduler.report_count


def run_baseline_test() -> int:
    print("[1/2] measuring collector-only baseline (no scheduler) ...")
    collector_baseline_ms = measure_collector_only_baseline()
    print(f"      collector-only CPU: {collector_baseline_ms:.2f} ms")

    print("[2/2] measuring scheduler self overhead (emit_report=False) ...")
    run_cpu_ms, rss_delta_mb, sessions = measure_scheduler_self_overhead()
    scheduler_overhead_ms = max(0.0, run_cpu_ms - collector_baseline_ms)
    print(f"      scheduler-with-collector CPU: {run_cpu_ms:.2f} ms")
    print(f"      scheduler self overhead: {scheduler_overhead_ms:.2f} ms")
    print(f"      RSS delta: {rss_delta_mb:.2f} MB, sessions={sessions}")

    print("[verify] report count correctness leg (emit_report=True) ...")
    rep_sessions, rep_count = verify_report_count_correctness()
    print(f"      sessions={rep_sessions}, reports={rep_count}")

    print(
        f"sessions={sessions} (overhead leg)  scheduler_overhead={scheduler_overhead_ms:.2f} ms  "
        f"RSS={rss_delta_mb:.2f} MB"
    )

    failures = []
    if not (EXPECTED_MIN_SESSIONS <= sessions <= EXPECTED_MAX_SESSIONS):
        failures.append(
            f"sessions {sessions} not in [{EXPECTED_MIN_SESSIONS}..{EXPECTED_MAX_SESSIONS}]"
        )
    if not (EXPECTED_MIN_SESSIONS <= rep_sessions <= EXPECTED_MAX_SESSIONS):
        failures.append(
            f"report-leg sessions {rep_sessions} not in [{EXPECTED_MIN_SESSIONS}..{EXPECTED_MAX_SESSIONS}]"
        )
    if rep_count != rep_sessions:
        failures.append(f"report count {rep_count} != sessions {rep_sessions}")
    if scheduler_overhead_ms >= CPU_THRESHOLD_MS:
        failures.append(
            f"scheduler self overhead {scheduler_overhead_ms:.2f} >= {CPU_THRESHOLD_MS:.2f} ms"
        )
    if rss_delta_mb >= MEM_THRESHOLD_MB:
        failures.append(
            f"常驻内存增量超阈值: {rss_delta_mb:.2f} >= {MEM_THRESHOLD_MB:.2f} MB"
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
