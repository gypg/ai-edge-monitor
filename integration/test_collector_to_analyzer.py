"""collector -> aggregator_analyzer integration.

Drives a `Collector` (force_dummy=True) for 10s @ 1Hz and verifies:
    - the analyzer received >= 9 metrics and >= 9 power frames
    - the latest PowerStatsFrame has the cross-module field set
    - the WindowSummary has the expected `timeline_*` fields
    - probe and power_source names are 'dummy' (force_dummy guarantees)
Emits the same PASS/FAIL convention as the other integration tests.
"""

from __future__ import annotations

import dataclasses
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from collector import Collector, CollectorConfig  # noqa: E402

DURATION_SEC = 10
INTERVAL_MS = 1000

EXPECTED_FRAME_FIELDS = {
    "window_start_ms", "window_end_ms", "count",
    "avg_power_watt", "p95_power_watt", "max_power_watt", "min_power_watt",
    "energy_joule", "fail_rate", "fallback_count", "source_name", "quality",
}
EXPECTED_SUMMARY_FIELDS = {
    "sample_count_metrics", "sample_count_power", "cpu_avg",
    "power_avg_watt", "timeline_cpu", "timeline_power_watt",
}


def _make_logger() -> logging.Logger:
    log = logging.getLogger("collector_to_analyzer")
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
    log.info("starting collector for %ds @ %dms (force_dummy=True)",
             DURATION_SEC, INTERVAL_MS)

    collector = Collector(CollectorConfig(
        interval_ms=INTERVAL_MS,
        force_dummy=True,
    ))
    log.info("collector wired: probe=%s power_source=%s",
             collector.probe_name, collector.power_source_name)

    collector.start()
    try:
        time.sleep(DURATION_SEC)
    finally:
        collector.stop()

    stats = collector.get_session_stats()
    summary = collector.analyzer.get_summary_dict()
    log.info("session stats: %s", stats)
    log.info("analyzer summary: metrics=%d power=%d cpu_avg=%s power_avg=%s",
             summary["sample_count_metrics"], summary["sample_count_power"],
             summary["cpu_avg"], summary["power_avg_watt"])

    failures = []
    expected_min = max(1, DURATION_SEC - 1)
    if stats["metrics_count"] < expected_min:
        failures.append(f"collector metrics_count {stats['metrics_count']} < {expected_min}")
    if stats["power_count"] < expected_min:
        failures.append(f"collector power_count {stats['power_count']} < {expected_min}")

    if summary["sample_count_metrics"] < expected_min:
        failures.append(f"analyzer metrics {summary['sample_count_metrics']} < {expected_min}")
    if summary["sample_count_power"] < expected_min:
        failures.append(f"analyzer power {summary['sample_count_power']} < {expected_min}")

    missing_summary = EXPECTED_SUMMARY_FIELDS - set(summary)
    if missing_summary:
        failures.append(f"summary missing fields: {sorted(missing_summary)}")

    # Pull a frame back via PowerStats snapshot to validate frame shape.
    frame = collector._power_stats.snapshot()
    actual_frame_fields = {f.name for f in dataclasses.fields(frame)}
    missing_frame = EXPECTED_FRAME_FIELDS - actual_frame_fields
    if missing_frame:
        failures.append(f"PowerStatsFrame missing fields: {sorted(missing_frame)}")

    if stats["probe_name"] != "dummy":
        failures.append(f"probe should be dummy, got {stats['probe_name']!r}")
    if stats["power_source_name"] != "dummy":
        failures.append(f"power source should be dummy, got {stats['power_source_name']!r}")

    if not failures:
        log.info("INTEGRATION RESULT: PASS")
        return 0
    log.error("INTEGRATION RESULT: FAIL")
    for f in failures:
        log.error("- %s", f)
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
