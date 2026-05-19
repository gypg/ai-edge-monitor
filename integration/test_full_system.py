"""Full-system integration: collector + scheduler + runtime_guardian.

Wires the three infrastructure modules together with Dummy sources and
runs for 60s. Halfway through, the test injects a synthetic high-load
condition into the guardian; the guardian's `on_degrade` callback flips
the scheduler to a slower cadence, the test then injects a low-load
condition and the `on_recover` callback restores normal cadence.

Verification:
- guardian observed >= 1 degrade and >= 1 recover transition
- scheduler.degraded toggled true during the high-load window
- scheduler ran >= 2 sessions and produced one PNG per session
- final report PNGs are valid (PNG magic + sidecar JSON)
- collector samples are present in the analyzer summary
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from collector import CollectorConfig  # noqa: E402
from runtime_guardian import GuardianConfig, RuntimeGuardian  # noqa: E402
from scheduler import PeriodicScheduler, ScheduleConfig  # noqa: E402
from visualizer import plot_report  # noqa: E402

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ARTIFACTS = ROOT / "integration" / "_full_system_artifacts"
TOTAL_SEC = 60


def _make_logger() -> logging.Logger:
    log = logging.getLogger("full_system")
    log.setLevel(logging.INFO)
    if not log.handlers:
        h = logging.StreamHandler(stream=sys.stdout)
        h.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s | %(message)s"
        ))
        log.addHandler(h)
        log.propagate = False
    return log


def run() -> int:
    log = _make_logger()
    if ARTIFACTS.exists():
        shutil.rmtree(ARTIFACTS, ignore_errors=True)

    scheduler = PeriodicScheduler(
        collector_config=CollectorConfig(interval_ms=500, force_dummy=True),
        schedule_config=ScheduleConfig(
            cycle_period_sec=12.0,
            collect_duration_sec=8.0,
            emit_report=True,
            report_dir=ARTIFACTS,
            report_prefix="session",
            degraded_cycle_period_sec=20.0,
        ),
        report_fn=plot_report,
    )

    guardian = RuntimeGuardian(
        GuardianConfig(
            interval_sec=0.5,
            cpu_percent_high=3.0,
            cpu_percent_low=2.0,
            rss_mb_high=50.0,
            rss_mb_low=40.0,
            test_mode=True,
        ),
        on_degrade=lambda h: scheduler.degrade(),
        on_recover=lambda h: scheduler.recover(),
    )

    log.info("starting full system: scheduler + guardian (60s)")
    scheduler.schedule()
    guardian.start()

    # Inject high load at t=20s, hold for 15s, then drop to recover.
    t0 = time.monotonic()
    inject_high_at = 20.0
    inject_low_at = 35.0
    saw_degrade_during_high = False
    end_at = t0 + TOTAL_SEC
    high_injected = False
    low_injected = False
    while time.monotonic() < end_at:
        elapsed = time.monotonic() - t0
        if not high_injected and elapsed >= inject_high_at:
            log.info("injecting high load (cpu=8%%, rss=80MB)")
            guardian.inject_test_load(cpu_percent=8.0, rss_mb=80.0)
            high_injected = True
        if (
            high_injected
            and not low_injected
            and elapsed >= inject_low_at
        ):
            log.info("injecting low load (cpu=0.5%%, rss=20MB)")
            guardian.inject_test_load(cpu_percent=0.5, rss_mb=20.0)
            low_injected = True
        if (
            high_injected
            and not low_injected
            and scheduler.is_degraded
        ):
            saw_degrade_during_high = True
        time.sleep(0.5)

    guardian.stop()
    scheduler.stop()

    health = guardian.get_health()
    log.info("guardian health: %s", health)
    log.info(
        "scheduler stats: sessions=%d reports=%d",
        scheduler.session_count, scheduler.report_count,
    )

    failures = []
    if health["degrade_count"] < 1:
        failures.append(f"guardian degrade_count {health['degrade_count']} < 1")
    if health["recover_count"] < 1:
        failures.append(f"guardian recover_count {health['recover_count']} < 1")
    if not saw_degrade_during_high:
        failures.append("scheduler.is_degraded never observed True during high-load window")
    if scheduler.session_count < 2:
        failures.append(f"scheduler.session_count {scheduler.session_count} < 2")
    if scheduler.report_count != scheduler.session_count:
        failures.append(
            f"reports {scheduler.report_count} != sessions {scheduler.session_count}"
        )

    for path in scheduler.reports:
        if not path.is_file():
            failures.append(f"missing report: {path}")
            continue
        with open(path, "rb") as fh:
            if fh.read(8) != PNG_MAGIC:
                failures.append(f"{path}: bad PNG header")
        sidecar = path.with_suffix(path.suffix + ".json")
        if not sidecar.is_file():
            failures.append(f"missing sidecar: {sidecar}")
            continue
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"{sidecar}: {exc}")
            continue
        if "timeline_cpu" not in payload:
            failures.append(f"{sidecar}: missing timeline_cpu")
        if payload.get("sample_count_metrics", 0) < 5:
            failures.append(
                f"{sidecar}: sample_count_metrics {payload.get('sample_count_metrics')} < 5"
            )

    if not failures:
        log.info("INTEGRATION RESULT: PASS")
        return 0
    log.error("INTEGRATION RESULT: FAIL")
    for f in failures:
        log.error("- %s", f)
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
