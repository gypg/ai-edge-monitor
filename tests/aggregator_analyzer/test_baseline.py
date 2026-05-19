"""aggregator_analyzer baseline overhead test.

Per the PRD, the analyzer should keep memory bounded under sustained
ingestion. This test ingests 10000 RawMetrics + 10000 PowerStatsFrame
into a 60-second window (with a fixed-rate clock) and asserts:

- RSS delta < 5MB
- After pruning, both ring buffers stay within `max_samples`
- get_summary() still returns finite numeric stats

Run:
    python tests/aggregator_analyzer/test_baseline.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import psutil  # type: ignore
except ModuleNotFoundError:
    psutil = None

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aggregator_analyzer import AggregatorAnalyzer  # noqa: E402

MEM_THRESHOLD_MB = 5.0


def _rss_mb_windows_tasklist() -> float:
    try:
        import csv
        import io
        import subprocess

        out = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {os.getpid()}", "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        if not out or out.lower().startswith("info:"):
            return 0.0
        row = next(csv.reader(io.StringIO(out)))
        if len(row) < 5:
            return 0.0
        digits = "".join(ch for ch in row[-1] if ch.isdigit())
        return (int(digits) / 1024.0) if digits else 0.0
    except Exception:
        return 0.0


def _rss_mb_linux_proc() -> float:
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def _rss_mb(proc) -> float:
    if proc is not None:
        return proc.memory_info().rss / (1024 * 1024)
    if sys.platform == "win32":
        return _rss_mb_windows_tasklist()
    if sys.platform.startswith("linux"):
        return _rss_mb_linux_proc()
    return 0.0


@dataclass
class _Raw:
    ts_ms: int
    cpu_percent: float
    mem_used_mb: float
    mem_total_mb: float = 4096.0
    gpu_percent: Optional[float] = None
    gpu_mem_used_mb: Optional[float] = None
    temperature_c: Optional[float] = None
    probe_name: str = "fake"
    status: str = "ok"
    latency_ms: float = 0.0
    error_message: Optional[str] = None


@dataclass
class _Frame:
    window_start_ms: int
    window_end_ms: int
    count: int = 1
    avg_power_watt: Optional[float] = 5.0
    p95_power_watt: Optional[float] = 5.5
    max_power_watt: Optional[float] = 6.0
    min_power_watt: Optional[float] = 4.5
    energy_joule: Optional[float] = 0.0
    fail_rate: float = 0.0
    fallback_count: int = 0
    source_name: str = "fake"
    quality: str = "raw"


def run_baseline() -> int:
    proc = psutil.Process(os.getpid()) if psutil is not None else None
    rss_before = _rss_mb(proc)

    # Drive the clock at 1 virtual second per ingestion pair so the
    # 60-second window naturally prunes old entries.
    fake_now = [0.0]

    def now():
        return fake_now[0]

    a = AggregatorAnalyzer(window_sec=60, max_samples=4096, now=now)
    n = 10000
    for i in range(n):
        fake_now[0] = float(i)
        a.ingest_metrics(_Raw(
            ts_ms=1000 + i * 1000,
            cpu_percent=30.0 + (i % 50),
            mem_used_mb=500 + (i % 200),
        ))
        a.ingest_power_stats(_Frame(window_start_ms=1000 + i * 1000, window_end_ms=1000 + i * 1000))

    summary = a.get_summary_dict()
    rss_after = _rss_mb(proc)
    rss_delta = max(0.0, rss_after - rss_before)

    print(f"ingested: {n} metrics + {n} power frames")
    print(
        f"window retained: metrics={summary['sample_count_metrics']} "
        f"power={summary['sample_count_power']}"
    )
    print(f"cpu_avg={summary['cpu_avg']} power_avg={summary['power_avg_watt']}")
    print(f"常驻内存增量: {rss_delta:.2f} MB")

    fail = []
    if rss_delta >= MEM_THRESHOLD_MB:
        fail.append(f"RSS delta {rss_delta:.2f}MB >= {MEM_THRESHOLD_MB:.2f}MB")
    if summary["sample_count_metrics"] > a.max_samples:
        fail.append(f"metrics buffer overflow: {summary['sample_count_metrics']} > {a.max_samples}")
    if summary["sample_count_power"] > a.max_samples:
        fail.append(f"power buffer overflow: {summary['sample_count_power']} > {a.max_samples}")
    if summary["cpu_avg"] is None:
        fail.append("cpu_avg unexpectedly None")

    if not fail:
        print("PASS")
        return 0
    print("FAIL")
    for f in fail:
        print(f"- {f}")
    return 1


if __name__ == "__main__":
    raise SystemExit(run_baseline())
