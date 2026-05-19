"""collector — lifecycle manager for platform + power samplers.

`Collector` owns one `PlatformSampler` and one `PowerSampler`, wires their
on_sample callbacks into an `AggregatorAnalyzer`, and exposes a unified
start/stop API. It is *not* a scheduler; it just runs until stopped. Use
`scheduler.PeriodicScheduler` to drive collection sessions on a cadence.

Source selection:
    - When `config.force_dummy=True` the collector skips real-source
      probing and uses DummyProbe + DummySource. This is the default for
      tests/CI.
    - Otherwise it calls `select_default_probe(prefer)` and
      `select_default_source(prefer)`, which already handle their own
      Dummy fallback when no real source is available on the host.

The collector keeps an internal `PowerStats` so it can produce
`PowerStatsFrame`s on every reading without forcing the analyzer to do
the windowing twice.
"""

from .collector import Collector, CollectorConfig

__all__ = ["Collector", "CollectorConfig"]
