"""Run idle / inference / throttled scenarios and emit reports.

Each scenario is driven by `PlatformSampler(DummyProbe)` and
`PowerSampler(DummySource)` for `--duration-sec` (default 60s) at 1Hz
in parallel, sharing a `Scenario` instance so CPU/temp on the platform
side stay phase-locked with power on the power side. After collection,
`AggregatorAnalyzer.get_summary_dict()` is fed to `plot_report()` to
produce a PNG + JSON sidecar in `docs/test_report/scenarios/`.

Run:
    python examples/generate_scenario_reports.py
    python examples/generate_scenario_reports.py --duration-sec 60 \
        --output-dir docs/test_report/scenarios
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aggregator_analyzer import AggregatorAnalyzer  # noqa: E402
from platform_adapter import DummyProbe, PlatformSampler  # noqa: E402
from power_monitor import DummySource, PowerSampler, PowerStats  # noqa: E402
from scenarios import make_scenario  # noqa: E402
from visualizer import plot_report  # noqa: E402

SCENARIOS = ("idle", "inference", "throttled")
DEFAULT_DURATION_SEC = 60
DEFAULT_INTERVAL_MS = 1000
DEFAULT_OUTPUT_DIR = ROOT / "docs" / "test_report" / "scenarios"


def run_scenario(
    name: str, duration_sec: int, interval_ms: int, output_dir: Path
) -> Dict[str, Any]:
    scenario = make_scenario(name, seed=42)
    probe = DummyProbe(scenario=scenario)
    source = DummySource(scenario=scenario)

    analyzer = AggregatorAnalyzer(window_sec=max(180, duration_sec * 4))
    power_stats = PowerStats(window_size=max(64, duration_sec))
    lock = threading.Lock()

    def on_metrics(raw):
        analyzer.ingest_metrics(raw)

    def on_power(reading):
        with lock:
            power_stats.ingest(reading)
            frame = power_stats.snapshot()
        analyzer.ingest_power_stats(frame)

    platform_sampler = PlatformSampler(probe=probe, interval_ms=interval_ms, on_sample=on_metrics)
    power_sampler = PowerSampler(source=source, interval_ms=interval_ms, on_sample=on_power)

    print(f"[{name}] starting samplers for {duration_sec}s @ {interval_ms}ms")
    t0 = time.monotonic()
    platform_sampler.start()
    power_sampler.start()
    try:
        time.sleep(duration_sec)
    finally:
        platform_sampler.stop()
        power_sampler.stop()
    elapsed = time.monotonic() - t0

    summary = analyzer.get_summary_dict()
    report_path = output_dir / f"report_{name}.png"
    plot_report(summary, report_path)

    print(
        f"[{name}] done in {elapsed:.1f}s — metrics={summary['sample_count_metrics']} "
        f"power={summary['sample_count_power']} cpu_avg={_fmt(summary['cpu_avg'])}% "
        f"cpu_max={_fmt(summary['cpu_max'])}% power_avg={_fmt(summary['power_avg_watt'])}W "
        f"power_max={_fmt(summary['power_max_watt'])}W energy={_fmt(summary['energy_joule'])}J"
    )

    return {
        "scenario": name,
        "duration_sec": duration_sec,
        "interval_ms": interval_ms,
        "metrics_count": summary["sample_count_metrics"],
        "power_count": summary["sample_count_power"],
        "cpu_avg": summary["cpu_avg"],
        "cpu_p95": summary["cpu_p95"],
        "cpu_max": summary["cpu_max"],
        "mem_used_avg_mb": summary["mem_used_avg_mb"],
        "mem_used_max_mb": summary["mem_used_max_mb"],
        "temp_max_c": summary["temp_max_c"],
        "power_avg_watt": summary["power_avg_watt"],
        "power_p95_watt": summary["power_p95_watt"],
        "power_max_watt": summary["power_max_watt"],
        "energy_joule": summary["energy_joule"],
        "report_path": str(report_path),
        "report_size_bytes": report_path.stat().st_size if report_path.is_file() else 0,
    }


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


def _parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="generate_scenario_reports")
    parser.add_argument("--duration-sec", type=int, default=DEFAULT_DURATION_SEC)
    parser.add_argument("--interval-ms", type=int, default=DEFAULT_INTERVAL_MS)
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--scenario",
        type=str,
        action="append",
        default=None,
        help="run only the named scenario (repeatable). default: all 3",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    names = args.scenario or list(SCENARIOS)

    results: List[Dict[str, Any]] = []
    for name in names:
        results.append(run_scenario(name, args.duration_sec, args.interval_ms, output_dir))

    summary_path = output_dir / "scenario_summary.json"
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("Comparison:")
    header = (
        f"{'scenario':12} {'cpu_avg':>8} {'cpu_max':>8} "
        f"{'pwr_avg':>8} {'pwr_max':>8} {'energy':>8} {'temp_max':>8}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['scenario']:12} {_fmt(r['cpu_avg']):>8} {_fmt(r['cpu_max']):>8} "
            f"{_fmt(r['power_avg_watt']):>8} {_fmt(r['power_max_watt']):>8} "
            f"{_fmt(r['energy_joule']):>8} {_fmt(r['temp_max_c']):>8}"
        )
    print()
    print(f"per-scenario summary written to: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
