"""platform_adapter -> metrics_collector integration demo.

Mirrors the power_monitor integration script so both modules exercise
the same shape of contract validation: probe -> RawMetrics ->
collector.collect_from_raw(...) -> MetricSnapshot.

Flow:
    1. select_default_probe(("procfs", "psutil")) — probe Linux /proc
       first, then psutil; fall back to DummyProbe on Windows/macOS dev
       hosts.
    2. PlatformSampler at 1Hz drives 10 readings.
    3. MockMetricsCollector validates RawMetrics shape and produces a
       MetricSnapshot with `power_watt=None` (per the v2 module split,
       power is filled later by aggregator_analyzer when it aligns a
       PowerStatsFrame from power_monitor).
    4. Pass / fail is decided by:
         - 10 readings received (allowing -1 jitter)
         - 0 RawMetrics shape violations
         - 0 MetricSnapshot fields populated from forbidden sources
           (in particular: no probe-side power leakage)

Run:
    python integration/test_adapter_to_collector.py
"""

from __future__ import annotations

import dataclasses
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from platform_adapter import (  # noqa: E402
    PlatformSampler,
    RawMetrics,
    select_default_probe,
)


DURATION_SEC = 10
INTERVAL_MS = 1000

EXPECTED_RAW_FIELDS = {
    "ts_ms", "cpu_percent", "mem_used_mb", "mem_total_mb",
    "gpu_percent", "gpu_mem_used_mb", "temperature_c",
    "probe_name", "status", "latency_ms", "error_message",
}


@dataclass
class MetricSnapshot:
    """Local mirror of the cross-module MetricSnapshot from PRD §6.

    `power_watt` is intentionally optional and filled by aggregator_analyzer
    when it aligns a PowerStatsFrame from power_monitor.
    """

    ts_ms: int
    cpu_percent: float
    mem_used_mb: float
    mem_total_mb: float
    gpu_percent: Optional[float]
    gpu_mem_used_mb: Optional[float]
    power_watt: Optional[float]
    temperature_c: Optional[float]
    device_id: str
    tags: Dict[str, str] = field(default_factory=dict)


class MockMetricsCollector:
    def __init__(self, log: logging.Logger, device_id: str = "dev0") -> None:
        self._log = log
        self._device_id = device_id
        self.received: List[MetricSnapshot] = []
        self.shape_violations: List[str] = []

    def collect_from_raw(self, raw: RawMetrics) -> MetricSnapshot:
        actual = {f.name for f in dataclasses.fields(raw)}
        missing = EXPECTED_RAW_FIELDS - actual
        if missing:
            msg = f"RawMetrics missing fields: {sorted(missing)}"
            self.shape_violations.append(msg)
            self._log.error("contract violation: %s", msg)
        if "power_watt" in actual:
            msg = "RawMetrics must NOT carry power_watt (owned by power_monitor)"
            self.shape_violations.append(msg)
            self._log.error("contract violation: %s", msg)

        snap = MetricSnapshot(
            ts_ms=raw.ts_ms,
            cpu_percent=raw.cpu_percent,
            mem_used_mb=raw.mem_used_mb,
            mem_total_mb=raw.mem_total_mb,
            gpu_percent=raw.gpu_percent,
            gpu_mem_used_mb=raw.gpu_mem_used_mb,
            power_watt=None,
            temperature_c=raw.temperature_c,
            device_id=self._device_id,
            tags={"probe": raw.probe_name, "status": raw.status},
        )
        self.received.append(snap)
        self._log.info(
            "snapshot: ts=%d cpu=%.2f%% mem=%.0f/%.0fMB temp=%s probe=%s status=%s latency=%.2fms",
            snap.ts_ms, snap.cpu_percent, snap.mem_used_mb, snap.mem_total_mb,
            "None" if snap.temperature_c is None else f"{snap.temperature_c:.1f}C",
            raw.probe_name, raw.status, raw.latency_ms,
        )
        return snap


def _make_logger() -> logging.Logger:
    log = logging.getLogger("adapter_to_collector")
    log.setLevel(logging.INFO)
    if not log.handlers:
        h = logging.StreamHandler(stream=sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s"))
        log.addHandler(h)
        log.propagate = False
    return log


def run() -> int:
    log = _make_logger()

    probe = select_default_probe(prefer=("procfs", "psutil"))
    caps = probe.detect_caps()
    log.info(
        "selected probe: name=%s class=%s available=%s caps=%s",
        probe.name, type(probe).__name__, probe.is_available(), caps,
    )
    if probe.name not in ("procfs", "psutil"):
        log.warning(
            "neither procfs nor psutil is available on this host; falling back to %s. "
            "Install psutil or run on Linux for real probe coverage.",
            probe.name,
        )

    collector = MockMetricsCollector(log)
    sampler = PlatformSampler(
        probe=probe,
        interval_ms=INTERVAL_MS,
        on_sample=lambda raw: collector.collect_from_raw(raw),
    )

    log.info("starting sampler: duration=%ds interval=%dms", DURATION_SEC, INTERVAL_MS)
    sampler.start()
    try:
        time.sleep(DURATION_SEC)
    finally:
        sampler.stop()
    log.info("sampler stopped: total_samples=%d last_jitter_ms=%.2f",
             sampler.sample_count, sampler.last_jitter_ms)

    received = len(collector.received)
    violations = collector.shape_violations
    log.info("collector received %d snapshot(s); shape violations=%d", received, len(violations))

    expected_min = max(1, DURATION_SEC - 1)
    ok = received >= expected_min and not violations
    if ok:
        log.info("INTEGRATION RESULT: PASS")
        return 0
    log.error("INTEGRATION RESULT: FAIL")
    if received < expected_min:
        log.error("- snapshot count %d below expected minimum %d", received, expected_min)
    for v in violations:
        log.error("- %s", v)
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
