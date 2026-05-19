"""End-to-end integration: collect -> analyze -> report.

Flow:
    1. Drive `PlatformSampler` and `PowerSampler` (real sources by
       default, Dummy fallback) in parallel.
    2. Each tick, push the reading into `AggregatorAnalyzer`.
    3. After collection, call `get_summary_dict()` and pass it to
       `visualizer.plot_report()` to produce a PNG report.
    4. Verify the PNG is valid, the JSON sidecar is parseable, and at
       least `duration_sec - 1` samples were captured for each side.
       Emit a single JSON status object and exit 0 on PASS, 1 on FAIL.

CLI:
    python integration/test_e2e_collect_to_report.py \
        --duration-sec 30 --interval-ms 1000 \
        --output-dir docs/test_report/artifacts \
        [--force-dummy]

Defaults preserve the previous behavior (10s, 1Hz, integration/ dir)
when no flags are given, so older invocations keep working.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aggregator_analyzer import AggregatorAnalyzer  # noqa: E402
from platform_adapter import (  # noqa: E402
    DummyProbe,
    PlatformSampler,
    select_default_probe,
)
from power_monitor import (  # noqa: E402
    DummySource,
    PowerSampler,
    PowerStats,
    select_default_source,
)
from visualizer import plot_report  # noqa: E402


DEFAULT_DURATION_SEC = 10
DEFAULT_INTERVAL_MS = 1000
DEFAULT_OUTPUT_DIR = ROOT / "integration"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _make_logger() -> logging.Logger:
    log = logging.getLogger("e2e")
    log.setLevel(logging.INFO)
    if not log.handlers:
        h = logging.StreamHandler(stream=sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s"))
        log.addHandler(h)
        log.propagate = False
    return log


def _parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="e2e", description=__doc__)
    parser.add_argument("--duration-sec", type=int, default=DEFAULT_DURATION_SEC)
    parser.add_argument("--interval-ms", type=int, default=DEFAULT_INTERVAL_MS)
    parser.add_argument(
        "--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR),
        help="directory where test_report.png and its JSON sidecar are written",
    )
    parser.add_argument(
        "--force-dummy", action="store_true",
        help="skip real source probing; use DummyProbe + DummySource (CI default)",
    )
    return parser.parse_args(argv)


def run(argv=None) -> int:
    args = _parse_args(argv)
    duration_sec = args.duration_sec
    interval_ms = args.interval_ms
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    log = _make_logger()
    log.info(
        "e2e: collect -> analyze -> report "
        "(duration=%ds, interval=%dms, out_dir=%s, force_dummy=%s)",
        duration_sec,
        interval_ms,
        out_dir,
        args.force_dummy,
    )

    if args.force_dummy:
        probe = DummyProbe()
        source = DummySource()
    else:
        probe = select_default_probe(prefer=("procfs", "psutil"))
        source = select_default_source(prefer=("sysfs",))

    log.info(
        "selected probe: name=%s class=%s",
        probe.name,
        type(probe).__name__,
    )
    log.info(
        "selected power source: name=%s class=%s",
        source.name,
        type(source).__name__,
    )
    if probe.name == "dummy":
        log.warning(
            "platform probe falling back to DummyProbe — "
            "real CPU/mem readings not available"
        )
    if source.name == "dummy":
        log.warning(
            "power source falling back to DummySource — "
            "real power readings not available"
        )

    analyzer = AggregatorAnalyzer(window_sec=max(120, duration_sec * 4))
    power_stats = PowerStats(window_size=max(64, duration_sec))
    lock = threading.Lock()

    def on_raw_metrics(raw):
        analyzer.ingest_metrics(raw)

    def on_power_reading(reading):
        with lock:
            power_stats.ingest(reading)
            frame = power_stats.snapshot()
        analyzer.ingest_power_stats(frame)

    platform_sampler = PlatformSampler(
        probe=probe,
        interval_ms=interval_ms,
        on_sample=on_raw_metrics,
    )
    power_sampler = PowerSampler(
        source=source,
        interval_ms=interval_ms,
        on_sample=on_power_reading,
    )

    platform_sampler.start()
    power_sampler.start()
    try:
        time.sleep(duration_sec)
    finally:
        platform_sampler.stop()
        power_sampler.stop()

    log.info("samplers stopped: platform=%d power=%d",
             platform_sampler.sample_count, power_sampler.sample_count)

    summary = analyzer.get_summary_dict()
    log.info(
        "summary: metrics=%d power=%d cpu_avg=%s cpu_p95=%s cpu_max=%s "
        "power_avg=%s power_p95=%s power_max=%s energy=%s quality=%s",
        summary["sample_count_metrics"], summary["sample_count_power"],
        summary["cpu_avg"], summary["cpu_p95"], summary["cpu_max"],
        summary["power_avg_watt"], summary["power_p95_watt"], summary["power_max_watt"],
        summary["energy_joule"], summary["power_quality_worst"],
    )

    out_path = out_dir / "test_report.png"
    written = plot_report(summary, out_path)
    log.info("report written: %s", written)

    failures = []
    p = Path(written)
    if not p.is_file():
        failures.append(f"report file missing: {p}")
    else:
        if p.stat().st_size < 100:
            failures.append(f"report file too small: {p.stat().st_size} bytes")
        with open(p, "rb") as fh:
            head = fh.read(8)
        if head != PNG_MAGIC:
            failures.append(f"PNG magic header mismatch: {head!r}")

    sidecar = p.with_suffix(p.suffix + ".json")
    sidecar_payload: Dict[str, Any] = {}
    if not sidecar.is_file():
        failures.append(f"json sidecar missing: {sidecar}")
    else:
        try:
            sidecar_payload = json.loads(sidecar.read_text(encoding="utf-8"))
            if "timeline_cpu" not in sidecar_payload:
                failures.append("sidecar missing timeline_cpu")
            if "timeline_power_watt" not in sidecar_payload:
                failures.append("sidecar missing timeline_power_watt")
        except json.JSONDecodeError as exc:
            failures.append(f"sidecar not valid JSON: {exc}")

    expected_min = max(1, duration_sec - 1)
    if summary["sample_count_metrics"] < expected_min:
        failures.append(f"metrics samples {summary['sample_count_metrics']} < {expected_min}")
    if summary["sample_count_power"] < expected_min:
        failures.append(f"power samples {summary['sample_count_power']} < {expected_min}")

    result: Dict[str, Any] = {
        "result": "PASS" if not failures else "FAIL",
        "report_path": str(p),
        "report_size_bytes": p.stat().st_size if p.is_file() else 0,
        "duration_sec": duration_sec,
        "interval_ms": interval_ms,
        "probe_name": probe.name,
        "power_source_name": source.name,
        "metrics_count": summary["sample_count_metrics"],
        "power_count": summary["sample_count_power"],
        "cpu_avg": summary["cpu_avg"],
        "cpu_p95": summary["cpu_p95"],
        "cpu_max": summary["cpu_max"],
        "power_avg_watt": summary["power_avg_watt"],
        "power_p95_watt": summary["power_p95_watt"],
        "power_max_watt": summary["power_max_watt"],
        "energy_joule": summary["energy_joule"],
        "power_quality_worst": summary["power_quality_worst"],
        "render_backend": sidecar_payload.get("_render_backend"),
        "failures": failures,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(run())
