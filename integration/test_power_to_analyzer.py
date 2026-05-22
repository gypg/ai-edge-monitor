"""Minimal power_monitor -> aggregator_analyzer integration demo.

Flow demonstrated by this script:
    1. Probe a real `PowerSource` (sysfs first; DummySource fallback when
       `/sys/class/power_supply` is absent, e.g. on Windows or hosts
       without a battery driver).
    2. Drive a `PowerSampler` for 10 seconds at 1 Hz.
    3. After every reading, push it into `PowerStats` and call a
       `MockAggregatorAnalyzer.ingest_power_stats(frame)` with the latest
       `PowerStatsFrame`. The mock stands in for the real
       `aggregator_analyzer` module which has not been implemented yet.
    4. Verify each frame matches the field contract documented in
       `docs/prd/aggregator_analyzer.md` and
       `docs/prd/README.md` (cross-module data structures).

Run:
    python integration/test_power_to_analyzer.py

Tip:
    On Windows, prepend `PYTHONIOENCODING=utf-8` if the default code page
    is GBK and you want clean Chinese in any string output (this script
    prints ASCII-only by default).
"""

from __future__ import annotations

import dataclasses
import logging
import sys
import threading
import time
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from power_monitor import (  # noqa: E402  (path setup above)
    PowerReading,
    PowerSampler,
    PowerStats,
    PowerStatsFrame,
    select_default_source,
)

DURATION_SEC = 10
INTERVAL_MS = 1000

EXPECTED_FRAME_FIELDS = {
    "window_start_ms",
    "window_end_ms",
    "count",
    "avg_power_watt",
    "p95_power_watt",
    "max_power_watt",
    "min_power_watt",
    "energy_joule",
    "fail_rate",
    "fallback_count",
    "source_name",
    "quality",
}


class MockAggregatorAnalyzer:
    """Stand-in for the real aggregator_analyzer module.

    Implements only the `ingest_power_stats(frame)` method declared in
    `docs/prd/aggregator_analyzer.md`. Each call validates the frame
    shape, logs the contents, and stashes it for end-of-run inspection.
    """

    def __init__(self, log: logging.Logger) -> None:
        self._log = log
        self.received: List[PowerStatsFrame] = []
        self.shape_violations: List[str] = []

    def ingest_power_stats(self, frame: PowerStatsFrame) -> None:
        actual = {f.name for f in dataclasses.fields(frame)}
        missing = EXPECTED_FRAME_FIELDS - actual
        if missing:
            msg = f"frame missing fields: {sorted(missing)}"
            self.shape_violations.append(msg)
            self._log.error("contract violation: %s", msg)

        self.received.append(frame)
        self._log.info(
            "ingest_power_stats: count=%d avg=%s p95=%s max=%s energy=%s "
            "fail_rate=%.2f source=%s quality=%s window=[%d..%d]",
            frame.count,
            _fmt(frame.avg_power_watt, "W"),
            _fmt(frame.p95_power_watt, "W"),
            _fmt(frame.max_power_watt, "W"),
            _fmt(frame.energy_joule, "J"),
            frame.fail_rate,
            frame.source_name,
            frame.quality,
            frame.window_start_ms,
            frame.window_end_ms,
        )


def _fmt(value, unit: str) -> str:
    if value is None:
        return "None"
    return f"{value:.3f}{unit}"


def _make_logger() -> logging.Logger:
    log = logging.getLogger("power_to_analyzer")
    log.setLevel(logging.INFO)
    if not log.handlers:
        h = logging.StreamHandler(stream=sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s"))
        log.addHandler(h)
        log.propagate = False
    return log


def run() -> int:
    log = _make_logger()

    source = select_default_source(prefer=("sysfs",))
    log.info(
        "selected source: name=%s available=%s class=%s",
        source.name,
        source.is_available(),
        type(source).__name__,
    )
    if source.name != "sysfs":
        log.warning(
            "sysfs power supply not present on this host; falling back to %s. "
            "Run on a Linux device with /sys/class/power_supply for a real-source demo.",
            source.name,
        )

    stats = PowerStats(window_size=64)
    aggregator = MockAggregatorAnalyzer(log)
    lock = threading.Lock()

    def on_sample(reading: PowerReading) -> None:
        with lock:
            stats.ingest(reading)
            frame = stats.snapshot()
        log.info(
            "sample: ts=%d power=%s status=%s quality=%s latency=%.2fms",
            reading.ts_ms,
            _fmt(reading.power_watt, "W"),
            reading.status,
            reading.quality,
            reading.latency_ms,
        )
        aggregator.ingest_power_stats(frame)

    sampler = PowerSampler(source=source, interval_ms=INTERVAL_MS, on_sample=on_sample)

    log.info("starting sampler: duration=%ds interval=%dms", DURATION_SEC, INTERVAL_MS)
    sampler.start()
    try:
        time.sleep(DURATION_SEC)
    finally:
        sampler.stop()
    log.info(
        "sampler stopped: total_samples=%d last_jitter_ms=%.2f",
        sampler.sample_count,
        sampler.last_jitter_ms,
    )

    received = len(aggregator.received)
    violations = aggregator.shape_violations
    log.info("aggregator received %d frame(s); shape violations=%d", received, len(violations))

    expected_min = max(1, DURATION_SEC - 1)
    ok = received >= expected_min and not violations
    if ok:
        log.info("INTEGRATION RESULT: PASS")
        return 0

    log.error("INTEGRATION RESULT: FAIL")
    if received < expected_min:
        log.error("- frame count %d below expected minimum %d", received, expected_min)
    for v in violations:
        log.error("- %s", v)
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
