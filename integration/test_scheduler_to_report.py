"""scheduler -> visualizer integration.

Drives a `PeriodicScheduler` for ~20s with `cycle_period_sec=10` and
`collect_duration_sec=5`. Expects:
- exactly 2 finished sessions and 2 reports
- each report PNG has the PNG magic header
- each report has a JSON sidecar with `timeline_*` fields
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
from scheduler import PeriodicScheduler, ScheduleConfig  # noqa: E402
from visualizer import plot_report  # noqa: E402

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ARTIFACTS = ROOT / "integration" / "_scheduler_artifacts"


def _make_logger() -> logging.Logger:
    log = logging.getLogger("scheduler_to_report")
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
            cycle_period_sec=10.0,
            collect_duration_sec=5.0,
            emit_report=True,
            report_dir=ARTIFACTS,
            report_prefix="cycle",
        ),
        report_fn=plot_report,
    )

    log.info("scheduling 20s of cycle=10s collect=5s")
    scheduler.schedule()
    time.sleep(20.0)
    scheduler.stop()
    log.info("stopped: sessions=%d reports=%d",
             scheduler.session_count, scheduler.report_count)

    failures = []
    # cycle_period=10s, collect=5s, total run 20s. Both 2 and 3 sessions
    # are valid depending on whether the third cycle starts before
    # `stop()` fires (sleep wakeups can land on either side of the
    # boundary).
    if not (2 <= scheduler.session_count <= 3):
        failures.append(f"session_count {scheduler.session_count} not in [2..3]")
    if scheduler.report_count != scheduler.session_count:
        failures.append(
            f"report_count {scheduler.report_count} != sessions {scheduler.session_count}"
        )

    for path in scheduler.reports:
        if not path.is_file():
            failures.append(f"report missing: {path}")
            continue
        if path.stat().st_size < 100:
            failures.append(f"{path}: too small ({path.stat().st_size} B)")
        with open(path, "rb") as fh:
            head = fh.read(8)
        if head != PNG_MAGIC:
            failures.append(f"{path}: bad PNG header {head!r}")

        sidecar = path.with_suffix(path.suffix + ".json")
        if not sidecar.is_file():
            failures.append(f"sidecar missing: {sidecar}")
            continue
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"{sidecar}: not valid JSON ({exc})")
            continue
        for required in ("timeline_cpu", "timeline_power_watt"):
            if required not in payload:
                failures.append(f"{sidecar}: missing {required}")

    if not failures:
        log.info("INTEGRATION RESULT: PASS")
        return 0
    log.error("INTEGRATION RESULT: FAIL")
    for f in failures:
        log.error("- %s", f)
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
