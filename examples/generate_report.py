"""Generate a sample report from synthetic data.

Run:
    python examples/generate_report.py

Produces:
    examples/sample_report.png
    examples/sample_report.png.json
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aggregator_analyzer import AggregatorAnalyzer  # noqa: E402
from visualizer import plot_report  # noqa: E402


class _RawMetricsLike:
    __slots__ = (
        "ts_ms",
        "cpu_percent",
        "mem_used_mb",
        "mem_total_mb",
        "gpu_percent",
        "gpu_mem_used_mb",
        "temperature_c",
        "probe_name",
        "status",
        "latency_ms",
        "error_message",
    )

    def __init__(self, ts_ms, cpu_percent, mem_used_mb):
        self.ts_ms = ts_ms
        self.cpu_percent = cpu_percent
        self.mem_used_mb = mem_used_mb
        self.mem_total_mb = 4096.0
        self.gpu_percent = None
        self.gpu_mem_used_mb = None
        self.temperature_c = 50.0
        self.probe_name = "demo"
        self.status = "ok"
        self.latency_ms = 0.05
        self.error_message = None


class _PowerStatsLike:
    __slots__ = (
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
    )

    def __init__(self, ts_ms, avg_w, energy_j):
        self.window_start_ms = ts_ms
        self.window_end_ms = ts_ms
        self.count = 1
        self.avg_power_watt = avg_w
        self.p95_power_watt = avg_w * 1.05
        self.max_power_watt = avg_w * 1.1
        self.min_power_watt = avg_w * 0.9
        self.energy_joule = energy_j
        self.fail_rate = 0.0
        self.fallback_count = 0
        self.source_name = "demo"
        self.quality = "raw"


def main() -> int:
    analyzer = AggregatorAnalyzer(window_sec=120)
    base_ts_ms = int(time.time() * 1000)
    energy = 0.0
    for i in range(60):
        ts = base_ts_ms + i * 1000
        cpu = 30 + 20 * math.sin(i / 6.0) + (i % 7)
        mem = 800 + 80 * math.sin(i / 9.0)
        watt = 6 + 2 * math.sin(i / 5.0) + 0.05 * i
        energy += watt
        analyzer.ingest_metrics(_RawMetricsLike(ts, cpu, mem))
        analyzer.ingest_power_stats(_PowerStatsLike(ts, watt, energy))

    out = ROOT / "examples" / "sample_report.png"
    written = plot_report(analyzer.get_summary_dict(), out)
    print(f"sample report written to: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
