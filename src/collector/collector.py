"""Collector: thin lifecycle wrapper around the two samplers."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from aggregator_analyzer import AggregatorAnalyzer
from platform_adapter import (
    DummyProbe,
    PlatformProbe,
    PlatformSampler,
    select_default_probe,
)
from power_monitor import (
    DummySource,
    PowerSampler,
    PowerSource,
    PowerStats,
    select_default_source,
)


@dataclass
class CollectorConfig:
    """Collector configuration.

    Fields:
        interval_ms: sampling cadence for both samplers (default 1000).
        platform_prefer: probe priority list passed to
            `select_default_probe` when not forcing dummy mode.
        power_prefer: source priority list passed to
            `select_default_source`.
        force_dummy: when True, skip real-source probing.
        power_window_size: window size for the in-collector
            `PowerStats`; affects how often a fresh frame is produced.
    """

    interval_ms: int = 1000
    platform_prefer: Tuple[str, ...] = ("procfs", "psutil")
    power_prefer: Tuple[str, ...] = ("sysfs",)
    force_dummy: bool = False
    power_window_size: int = 64

    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "CollectorConfig":
        kwargs: Dict[str, Any] = {}
        if "interval_ms" in raw:
            kwargs["interval_ms"] = int(raw["interval_ms"])
        if "platform_prefer" in raw:
            kwargs["platform_prefer"] = tuple(raw["platform_prefer"])
        if "power_prefer" in raw:
            kwargs["power_prefer"] = tuple(raw["power_prefer"])
        if "force_dummy" in raw:
            kwargs["force_dummy"] = bool(raw["force_dummy"])
        if "power_window_size" in raw:
            kwargs["power_window_size"] = int(raw["power_window_size"])
        known = set(kwargs)
        kwargs["extra"] = {k: v for k, v in raw.items() if k not in known}
        return cls(**kwargs)


class Collector:
    """Owns the two samplers and feeds their output to an analyzer.

    Args:
        config: collector configuration.
        analyzer: shared analyzer; if None the collector creates one.
    """

    def __init__(
        self,
        config: Optional[CollectorConfig] = None,
        analyzer: Optional[AggregatorAnalyzer] = None,
    ) -> None:
        self.config = config or CollectorConfig()
        self.analyzer = analyzer or AggregatorAnalyzer(window_sec=300)

        if self.config.force_dummy:
            self._probe: PlatformProbe = DummyProbe()
            self._source: PowerSource = DummySource()
        else:
            self._probe = select_default_probe(prefer=self.config.platform_prefer)
            self._source = select_default_source(prefer=self.config.power_prefer)

        self._power_stats = PowerStats(window_size=max(8, self.config.power_window_size))
        self._power_lock = threading.Lock()

        self._platform_sampler = PlatformSampler(
            probe=self._probe,
            interval_ms=self.config.interval_ms,
            on_sample=self._on_metrics,
        )
        self._power_sampler = PowerSampler(
            source=self._source,
            interval_ms=self.config.interval_ms,
            on_sample=self._on_power_reading,
        )
        self._running = False
        self._counts_lock = threading.Lock()
        self._metrics_count = 0
        self._power_count = 0

    @property
    def probe_name(self) -> str:
        return self._probe.name

    @property
    def power_source_name(self) -> str:
        return self._source.name

    @property
    def is_running(self) -> bool:
        return self._running

    def get_session_stats(self) -> Dict[str, Any]:
        with self._counts_lock:
            return {
                "metrics_count": self._metrics_count,
                "power_count": self._power_count,
                "probe_name": self._probe.name,
                "power_source_name": self._source.name,
                "running": self._running,
            }

    def reset_session_stats(self) -> None:
        with self._counts_lock:
            self._metrics_count = 0
            self._power_count = 0

    def reset_analyzer(self) -> None:
        self.analyzer = AggregatorAnalyzer(window_sec=self.analyzer.window_sec)
        with self._power_lock:
            self._power_stats = PowerStats(window_size=self._power_stats.window_size)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._platform_sampler.start()
        self._power_sampler.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._platform_sampler.stop()
        self._power_sampler.stop()
        self._running = False

    def __enter__(self) -> "Collector":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def _on_metrics(self, raw) -> None:
        self.analyzer.ingest_metrics(raw)
        with self._counts_lock:
            self._metrics_count += 1

    def _on_power_reading(self, reading) -> None:
        with self._power_lock:
            self._power_stats.ingest(reading)
            frame = self._power_stats.snapshot()
        self.analyzer.ingest_power_stats(frame)
        with self._counts_lock:
            self._power_count += 1
