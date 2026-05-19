"""Sliding-window power statistics.

Tracks recent power readings and computes lightweight summary statistics.

The output dataclass `PowerStatsFrame` matches the cross-module contract
declared in `docs/prd/aggregator_analyzer.md` and `docs/prd/README.md` so
`AggregatorAnalyzer.ingest_power_stats(frame)` can consume it directly
without any field translation. The legacy alias `PowerStatsSnapshot` is
kept temporarily for callers built against the previous skeleton.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from statistics import mean
from typing import Deque, Optional

from .source import PowerReading, Quality


@dataclass
class PowerStatsFrame:
    """Window-level power statistics frame.

    Field set mirrors the cross-module data contract documented in the PRD:
        - window_start_ms / window_end_ms: timestamps of the oldest/newest
          reading kept in the window.
        - count: total readings in the window (incl. failed/unavailable).
        - avg/p95/max/min_power_watt: stats over readings with status="ok"
          and a non-None power_watt.
        - energy_joule: avg_power_watt * elapsed_seconds, when computable.
        - fail_rate: share of readings whose status != "ok".
        - fallback_count: cumulative source fallbacks observed (caller-fed).
        - source_name: name of the source the latest reading came from.
        - quality: worst quality observed in the window.
    """

    window_start_ms: int
    window_end_ms: int
    count: int
    avg_power_watt: Optional[float]
    p95_power_watt: Optional[float]
    max_power_watt: Optional[float]
    min_power_watt: Optional[float]
    energy_joule: Optional[float]
    fail_rate: float
    fallback_count: int = 0
    source_name: str = "unknown"
    quality: Quality = "unavailable"


# Backwards-compatible alias (deprecated). Prefer `PowerStatsFrame`.
PowerStatsSnapshot = PowerStatsFrame


_QUALITY_ORDER = {"raw": 3, "derived": 2, "estimated": 1, "unavailable": 0}


class PowerStats:
    """Sliding-window stats calculator.

    Args:
        window_size: Max number of recent samples retained.
    """

    def __init__(self, window_size: int = 60) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be > 0")
        self.window_size = window_size
        self._samples: Deque[PowerReading] = deque(maxlen=window_size)
        self._fallback_count = 0

    def ingest(self, reading: PowerReading) -> None:
        """Add one reading to the window.

        Readings with unavailable power are kept for count/fail_rate
        semantics, but excluded from power and energy calculations.
        """
        self._samples.append(reading)

    def note_fallback(self) -> None:
        """Caller-driven counter incremented on each source fallback."""
        self._fallback_count += 1

    def snapshot(self) -> PowerStatsFrame:
        """Compute summary over current window."""
        if not self._samples:
            return PowerStatsFrame(
                window_start_ms=0,
                window_end_ms=0,
                count=0,
                avg_power_watt=None,
                p95_power_watt=None,
                max_power_watt=None,
                min_power_watt=None,
                energy_joule=None,
                fail_rate=0.0,
                fallback_count=self._fallback_count,
                source_name="unknown",
                quality="unavailable",
            )

        first = self._samples[0]
        last = self._samples[-1]
        count = len(self._samples)
        fail = sum(1 for s in self._samples if s.status != "ok")
        fail_rate = fail / count

        worst_quality: Quality = "raw"
        for s in self._samples:
            if _QUALITY_ORDER[s.quality] < _QUALITY_ORDER[worst_quality]:
                worst_quality = s.quality

        values = [
            s.power_watt
            for s in self._samples
            if s.power_watt is not None and s.status == "ok"
        ]
        if not values:
            return PowerStatsFrame(
                window_start_ms=first.ts_ms,
                window_end_ms=last.ts_ms,
                count=count,
                avg_power_watt=None,
                p95_power_watt=None,
                max_power_watt=None,
                min_power_watt=None,
                energy_joule=None,
                fail_rate=fail_rate,
                fallback_count=self._fallback_count,
                source_name=last.source_name,
                quality=worst_quality,
            )

        sorted_values = sorted(values)
        idx = int((len(sorted_values) - 1) * 0.95)
        p95 = sorted_values[idx]
        avg = mean(values)

        elapsed_s = max(0.0, (last.ts_ms - first.ts_ms) / 1000.0)
        energy_joule = avg * elapsed_s if elapsed_s > 0 else 0.0

        return PowerStatsFrame(
            window_start_ms=first.ts_ms,
            window_end_ms=last.ts_ms,
            count=count,
            avg_power_watt=avg,
            p95_power_watt=p95,
            max_power_watt=max(values),
            min_power_watt=min(values),
            energy_joule=energy_joule,
            fail_rate=fail_rate,
            fallback_count=self._fallback_count,
            source_name=last.source_name,
            quality=worst_quality,
        )
