"""Cross-source aggregator and analyzer.

Consumes:
- `RawMetrics` from `platform_adapter` (CPU/mem/temp/GPU; no power)
- `PowerStatsFrame` from `power_monitor` (avg/p95/max power, energy, quality)

Maintains a time-windowed cache and produces a `WindowSummary` for the
visualizer / reporting layer.

Design notes:
- Two independent ring buffers (one per source) so a stall on one side
  cannot block ingestion on the other.
- A `now()` provider is injectable so tests can drive deterministic
  windowing without touching the system clock.
- Power values are taken from the *latest* `PowerStatsFrame`'s per-window
  stats rather than re-aggregated from raw `PowerSample`s, because
  `power_monitor` already handles unit normalization, fail rate, and
  quality propagation. Re-doing it here would either duplicate work or
  let bugs diverge between modules.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from statistics import mean
from threading import Lock
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

# Avoid hard imports — these modules might not exist in test fixtures.
# Type-hint via TYPE_CHECKING-style local names that accept any duck type.
RawMetricsLike = Any
PowerStatsFrameLike = Any


@dataclass
class WindowSummary:
    """Aggregated view over the configured window.

    Fields prefixed with `cpu_` / `mem_` / `temp_` come from RawMetrics.
    Fields prefixed with `power_` come from the most recent N
    PowerStatsFrame entries (themselves window summaries).

    Time-series fields (`timeline_*`) are kept short — they are intended
    for the visualizer to plot directly without round-tripping through a
    second aggregation pass.
    """

    window_sec: int
    sample_count_metrics: int
    sample_count_power: int

    cpu_avg: Optional[float] = None
    cpu_p95: Optional[float] = None
    cpu_max: Optional[float] = None

    mem_used_avg_mb: Optional[float] = None
    mem_used_max_mb: Optional[float] = None
    mem_total_mb: Optional[float] = None

    temp_max_c: Optional[float] = None

    power_avg_watt: Optional[float] = None
    power_p95_watt: Optional[float] = None
    power_max_watt: Optional[float] = None
    energy_joule: Optional[float] = None
    power_quality_worst: Optional[str] = None
    power_source_name: Optional[str] = None
    power_fail_rate_max: Optional[float] = None

    timeline_ts_ms: List[int] = field(default_factory=list)
    timeline_cpu: List[float] = field(default_factory=list)
    timeline_mem_used_mb: List[float] = field(default_factory=list)
    timeline_power_ts_ms: List[int] = field(default_factory=list)
    timeline_power_watt: List[float] = field(default_factory=list)


_QUALITY_ORDER = {"raw": 3, "derived": 2, "estimated": 1, "unavailable": 0}


class AggregatorAnalyzer:
    """Cross-source aggregator.

    Args:
        window_sec: Retention window in seconds for both ingestion paths.
        max_samples: Hard cap on per-source samples retained, to bound
            memory in face of bursty ingestion or paused readers.
        now: Optional clock function returning seconds (defaults to
            time.monotonic) — used for window pruning.
    """

    def __init__(
        self,
        window_sec: int = 60,
        max_samples: int = 4096,
        now: Optional[Callable[[], float]] = None,
    ) -> None:
        if window_sec <= 0:
            raise ValueError("window_sec must be > 0")
        if max_samples <= 0:
            raise ValueError("max_samples must be > 0")
        self.window_sec = window_sec
        self.max_samples = max_samples
        self._now = now or time.monotonic

        self._lock = Lock()
        self._metrics: Deque[Tuple[float, RawMetricsLike]] = deque(maxlen=max_samples)
        self._power: Deque[Tuple[float, PowerStatsFrameLike]] = deque(maxlen=max_samples)

    def ingest_metrics(self, raw: RawMetricsLike) -> None:
        """Store one `RawMetrics` reading.

        Readings whose `status != "ok"` are still kept (so callers can see
        ingestion liveness), but excluded from numeric stats by
        `_collect_metric_values()`.
        """
        ts = self._now()
        with self._lock:
            self._metrics.append((ts, raw))
            self._prune_locked()

    def ingest_power_stats(self, frame: PowerStatsFrameLike) -> None:
        """Store one `PowerStatsFrame`."""
        ts = self._now()
        with self._lock:
            self._power.append((ts, frame))
            self._prune_locked()

    def _prune_locked(self) -> None:
        cutoff = self._now() - self.window_sec
        while self._metrics and self._metrics[0][0] < cutoff:
            self._metrics.popleft()
        while self._power and self._power[0][0] < cutoff:
            self._power.popleft()

    def get_summary(self) -> WindowSummary:
        """Compute the current `WindowSummary` snapshot."""
        with self._lock:
            self._prune_locked()
            metrics_snapshot = list(self._metrics)
            power_snapshot = list(self._power)

        summary = WindowSummary(
            window_sec=self.window_sec,
            sample_count_metrics=len(metrics_snapshot),
            sample_count_power=len(power_snapshot),
        )

        cpu_vals = _collect_metric_values(metrics_snapshot, "cpu_percent")
        if cpu_vals:
            summary.cpu_avg = mean(cpu_vals)
            summary.cpu_p95 = _p95(cpu_vals)
            summary.cpu_max = max(cpu_vals)

        mem_used = _collect_metric_values(metrics_snapshot, "mem_used_mb")
        if mem_used:
            summary.mem_used_avg_mb = mean(mem_used)
            summary.mem_used_max_mb = max(mem_used)

        mem_total = _collect_metric_values(metrics_snapshot, "mem_total_mb")
        if mem_total:
            summary.mem_total_mb = max(mem_total)

        temp_vals = _collect_metric_values(metrics_snapshot, "temperature_c", allow_none=False)
        if temp_vals:
            summary.temp_max_c = max(temp_vals)

        if power_snapshot:
            avg_vals = [_get(f, "avg_power_watt") for _, f in power_snapshot]
            avg_vals = [v for v in avg_vals if v is not None]
            p95_vals = [_get(f, "p95_power_watt") for _, f in power_snapshot]
            p95_vals = [v for v in p95_vals if v is not None]
            max_vals = [_get(f, "max_power_watt") for _, f in power_snapshot]
            max_vals = [v for v in max_vals if v is not None]
            energy_vals = [_get(f, "energy_joule") for _, f in power_snapshot]
            energy_vals = [v for v in energy_vals if v is not None]
            fail_rates = [_get(f, "fail_rate") for _, f in power_snapshot]
            fail_rates = [v for v in fail_rates if v is not None]

            if avg_vals:
                summary.power_avg_watt = mean(avg_vals)
            if p95_vals:
                summary.power_p95_watt = max(p95_vals)
            if max_vals:
                summary.power_max_watt = max(max_vals)
            if energy_vals:
                summary.energy_joule = energy_vals[-1]
            if fail_rates:
                summary.power_fail_rate_max = max(fail_rates)

            qualities = [_get(f, "quality") for _, f in power_snapshot]
            qualities = [q for q in qualities if q is not None]
            if qualities:
                worst = qualities[0]
                for q in qualities[1:]:
                    if _QUALITY_ORDER.get(q, 0) < _QUALITY_ORDER.get(worst, 0):
                        worst = q
                summary.power_quality_worst = worst

            last_frame = power_snapshot[-1][1]
            summary.power_source_name = _get(last_frame, "source_name")

        # Timelines (chronological order, kept short for plotting).
        for _, raw in metrics_snapshot:
            ts_ms = _get(raw, "ts_ms")
            cpu = _get(raw, "cpu_percent")
            mem_used_mb = _get(raw, "mem_used_mb")
            if ts_ms is None or cpu is None or mem_used_mb is None:
                continue
            if _get(raw, "status") not in (None, "ok"):
                continue
            summary.timeline_ts_ms.append(int(ts_ms))
            summary.timeline_cpu.append(float(cpu))
            summary.timeline_mem_used_mb.append(float(mem_used_mb))

        for _, frame in power_snapshot:
            ts_ms = _get(frame, "window_end_ms")
            avg = _get(frame, "avg_power_watt")
            if ts_ms is None or avg is None:
                continue
            summary.timeline_power_ts_ms.append(int(ts_ms))
            summary.timeline_power_watt.append(float(avg))

        return summary

    def get_summary_dict(self) -> Dict[str, Any]:
        """Serialize the summary to a JSON-friendly dict."""
        s = self.get_summary()
        d = {
            "window_sec": s.window_sec,
            "sample_count_metrics": s.sample_count_metrics,
            "sample_count_power": s.sample_count_power,
            "cpu_avg": s.cpu_avg,
            "cpu_p95": s.cpu_p95,
            "cpu_max": s.cpu_max,
            "mem_used_avg_mb": s.mem_used_avg_mb,
            "mem_used_max_mb": s.mem_used_max_mb,
            "mem_total_mb": s.mem_total_mb,
            "temp_max_c": s.temp_max_c,
            "power_avg_watt": s.power_avg_watt,
            "power_p95_watt": s.power_p95_watt,
            "power_max_watt": s.power_max_watt,
            "energy_joule": s.energy_joule,
            "power_quality_worst": s.power_quality_worst,
            "power_source_name": s.power_source_name,
            "power_fail_rate_max": s.power_fail_rate_max,
            "timeline_ts_ms": list(s.timeline_ts_ms),
            "timeline_cpu": list(s.timeline_cpu),
            "timeline_mem_used_mb": list(s.timeline_mem_used_mb),
            "timeline_power_ts_ms": list(s.timeline_power_ts_ms),
            "timeline_power_watt": list(s.timeline_power_watt),
        }
        return d


def _get(obj: Any, name: str) -> Any:
    """Read attr from dataclass or key from dict, returning None if absent."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _collect_metric_values(
    snapshot: List[Tuple[float, RawMetricsLike]],
    field_name: str,
    allow_none: bool = False,
) -> List[float]:
    out: List[float] = []
    for _, raw in snapshot:
        if _get(raw, "status") not in (None, "ok"):
            continue
        v = _get(raw, field_name)
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int((len(s) - 1) * 0.95)
    return s[idx]
