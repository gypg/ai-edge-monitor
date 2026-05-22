from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from aggregator_analyzer import AggregatorAnalyzer
from collector import Collector, CollectorConfig
from scenarios import make_scenario
from storage_exporter import CsvExporter, JsonlExporter, SummaryExporter
from visualizer import plot_report

DEFAULT_DURATION_SEC = 30
DEFAULT_INTERVAL_MS = 1000
DEFAULT_OUTPUT_DIR = "reports/demo"
SCENARIOS = ("idle", "inference", "throttled")


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-edge-monitor")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="run one monitoring session")
    run_parser.add_argument("--duration", type=int, default=None)
    run_parser.add_argument("--interval", type=int, default=None)
    run_parser.add_argument("--out", type=str, default=None)
    run_parser.add_argument("--config", type=str, default=None)
    run_parser.add_argument("--force-dummy", action="store_true")
    run_parser.set_defaults(func=_run_command)

    report_parser = sub.add_parser("report", help="render report.png from summary.json")
    report_parser.add_argument("--input", type=str, required=True)
    report_parser.add_argument("--out", type=str, required=True)
    report_parser.set_defaults(func=_report_command)

    scenario_parser = sub.add_parser("scenario", help="generate reports for synthetic scenarios")
    scenario_parser.add_argument("--duration", type=int, default=60)
    scenario_parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_MS)
    scenario_parser.add_argument("--out", type=str, default="docs/test_report/scenarios")
    scenario_parser.add_argument("--scenario", action="append", choices=SCENARIOS, default=None)
    scenario_parser.set_defaults(func=_scenario_command)

    return parser


def _run_command(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    duration_sec = int(_pick(args.duration, config.get("duration_sec"), DEFAULT_DURATION_SEC))
    interval_ms = int(_pick(args.interval, config.get("interval_ms"), DEFAULT_INTERVAL_MS))
    output_dir = Path(str(_pick(args.out, config.get("output_dir"), DEFAULT_OUTPUT_DIR)))
    force_dummy = bool(args.force_dummy or config.get("force_dummy", False))

    if duration_sec <= 0:
        raise ValueError("--duration must be > 0")
    if interval_ms <= 0:
        raise ValueError("--interval must be > 0")

    analyzer = AggregatorAnalyzer(window_sec=max(120, duration_sec * 4))
    collector = Collector(
        CollectorConfig(
            interval_ms=interval_ms,
            force_dummy=force_dummy,
            power_window_size=max(8, duration_sec),
        ),
        analyzer=analyzer,
    )

    print(
        "starting monitor session: "
        f"duration={duration_sec}s interval={interval_ms}ms out={output_dir} "
        f"probe={collector.probe_name} power={collector.power_source_name}"
    )
    collector.start()
    try:
        time.sleep(duration_sec)
    finally:
        collector.stop()

    summary = analyzer.get_summary_dict()
    session_stats = collector.get_session_stats()
    summary.update(session_stats)

    metric_rows = _summary_to_metric_rows(summary)
    JsonlExporter(output_dir).write_metrics(metric_rows)
    CsvExporter(output_dir).write_metrics(metric_rows)
    SummaryExporter(output_dir).write_summary(summary)
    report_path = plot_report(summary, output_dir / "report.png")

    print(
        "monitor session complete: "
        f"metrics={summary['sample_count_metrics']} power={summary['sample_count_power']} "
        f"report={report_path}"
    )
    return 0


def _report_command(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.is_file():
        raise FileNotFoundError(f"summary file not found: {input_path}")
    summary = json.loads(input_path.read_text(encoding="utf-8"))
    report_path = plot_report(summary, Path(args.out))
    print(f"report written: {report_path}")
    return 0


def _scenario_command(args: argparse.Namespace) -> int:
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    names = args.scenario or list(SCENARIOS)
    results: List[Dict[str, Any]] = []
    for name in names:
        result = _run_scenario(name, int(args.duration), int(args.interval), output_dir)
        results.append(result)
    summary_path = output_dir / "scenario_summary.json"
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"scenario summary written: {summary_path}")
    return 0


def _run_scenario(name: str, duration_sec: int, interval_ms: int, output_dir: Path) -> Dict[str, Any]:
    from platform_adapter import DummyProbe
    from power_monitor import DummySource, PowerSampler, PowerStats
    from platform_adapter import PlatformSampler
    import threading

    scenario = make_scenario(name, seed=42)
    analyzer = AggregatorAnalyzer(window_sec=max(180, duration_sec * 4))
    power_stats = PowerStats(window_size=max(8, duration_sec))
    lock = threading.Lock()

    def on_metrics(raw: Any) -> None:
        analyzer.ingest_metrics(raw)

    def on_power(reading: Any) -> None:
        with lock:
            power_stats.ingest(reading)
            frame = power_stats.snapshot()
        analyzer.ingest_power_stats(frame)

    platform_sampler = PlatformSampler(
        probe=DummyProbe(scenario=scenario), interval_ms=interval_ms, on_sample=on_metrics
    )
    power_sampler = PowerSampler(
        source=DummySource(scenario=scenario), interval_ms=interval_ms, on_sample=on_power
    )
    platform_sampler.start()
    power_sampler.start()
    try:
        time.sleep(duration_sec)
    finally:
        platform_sampler.stop()
        power_sampler.stop()

    summary = analyzer.get_summary_dict()
    report_path = output_dir / f"report_{name}.png"
    plot_report(summary, report_path)
    return {
        "scenario": name,
        "duration_sec": duration_sec,
        "interval_ms": interval_ms,
        "metrics_count": summary["sample_count_metrics"],
        "power_count": summary["sample_count_power"],
        "cpu_avg": summary["cpu_avg"],
        "power_avg_watt": summary["power_avg_watt"],
        "energy_joule": summary["energy_joule"],
        "report_path": str(report_path),
    }


def _summary_to_metric_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    ts_values = list(summary.get("timeline_ts_ms") or [])
    cpu_values = list(summary.get("timeline_cpu") or [])
    mem_values = list(summary.get("timeline_mem_used_mb") or [])
    power_ts_values = list(summary.get("timeline_power_ts_ms") or [])
    power_values = list(summary.get("timeline_power_watt") or [])
    rows: List[Dict[str, Any]] = []
    count = max(len(ts_values), len(power_ts_values))
    for i in range(count):
        rows.append(
            {
                "ts_ms": _at(ts_values, i),
                "cpu_percent": _at(cpu_values, i),
                "mem_used_mb": _at(mem_values, i),
                "power_ts_ms": _at(power_ts_values, i),
                "avg_power_watt": _at(power_values, i),
                "probe_name": summary.get("probe_name"),
                "power_source_name": summary.get("power_source_name"),
            }
        )
    return rows


def _at(values: List[Any], index: int) -> Any:
    if index >= len(values):
        return None
    return values[index]


def _load_config(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"config file not found: {config_path}")
    if config_path.suffix.lower() not in (".json", ""):
        raise ValueError("--config currently supports JSON files")
    loaded = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("config file must contain a JSON object")
    return loaded


def _pick(cli_value: Any, config_value: Any, default: Any) -> Any:
    if cli_value is not None:
        return cli_value
    if config_value is not None:
        return config_value
    return default


if __name__ == "__main__":
    raise SystemExit(main())
