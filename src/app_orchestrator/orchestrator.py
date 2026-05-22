from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from aggregator_analyzer import AggregatorAnalyzer
from collector import Collector, CollectorConfig
from config_manager import ConfigError, MonitorConfig
from storage_exporter import CsvExporter, JsonlExporter, SummaryExporter
from visualizer import plot_report


@dataclass
class MonitoringResult:
    output_dir: Path
    metrics_jsonl: Path
    metrics_csv: Path
    summary_json: Path
    report_png: Path
    metrics_count: int
    power_count: int
    probe_name: str
    power_source_name: str


class Orchestrator:
    def __init__(self, config: MonitorConfig) -> None:
        self.config = config

    def run(self) -> MonitoringResult:
        output_dir = Path(self.config.output_dir)
        if output_dir.exists() and not output_dir.is_dir():
            raise ConfigError(f"output path is not a directory: {output_dir}")

        analyzer = AggregatorAnalyzer(window_sec=max(120, self.config.duration_sec * 4))
        collector = Collector(
            CollectorConfig(
                interval_ms=self.config.interval_ms,
                platform_prefer=_platform_prefer(self.config.device),
                force_dummy=self.config.force_dummy,
                power_window_size=max(8, self.config.duration_sec),
            ),
            analyzer=analyzer,
        )

        collector.start()
        try:
            time.sleep(self.config.duration_sec)
        finally:
            collector.stop()

        summary = analyzer.get_summary_dict()
        session_stats = collector.get_session_stats()
        summary.update(session_stats)
        metric_rows = summary_to_metric_rows(summary)

        metrics_jsonl = output_dir / "metrics.jsonl"
        metrics_csv = output_dir / "metrics.csv"
        summary_json = output_dir / "summary.json"
        report_png = output_dir / "report.png"

        if "jsonl" in self.config.exporters:
            metrics_jsonl = JsonlExporter(output_dir).write_metrics(metric_rows)
        if "csv" in self.config.exporters:
            metrics_csv = CsvExporter(output_dir).write_metrics(metric_rows)
        if "summary" in self.config.exporters:
            summary_json = SummaryExporter(output_dir).write_summary(summary)
        if "png" in self.config.exporters:
            report_png = Path(plot_report(summary, report_png))

        return MonitoringResult(
            output_dir=output_dir,
            metrics_jsonl=metrics_jsonl,
            metrics_csv=metrics_csv,
            summary_json=summary_json,
            report_png=report_png,
            metrics_count=int(summary.get("sample_count_metrics") or 0),
            power_count=int(summary.get("sample_count_power") or 0),
            probe_name=str(summary.get("probe_name") or "unknown"),
            power_source_name=str(summary.get("power_source_name") or "unknown"),
        )


def summary_to_metric_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
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


def _platform_prefer(device: str) -> tuple:
    if device == "nvidia-smi":
        return ("nvidia-smi", "procfs", "psutil")
    return ("procfs", "psutil")


def _at(values: List[Any], index: int) -> Any:
    if index >= len(values):
        return None
    return values[index]
