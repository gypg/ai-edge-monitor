"""Power monitor package public API.

This package contains a lightweight, platform-agnostic skeleton for power
monitoring. It is designed to run on Python 3.8+ and focuses on low-overhead
sampling and simple rolling statistics.
"""

from .source import (
    DummySource,
    PowerReading,
    PowerSource,
    SysfsPowerSource,
    select_default_source,
)
from .sampler import PowerSampler
from .stats import PowerStats, PowerStatsFrame, PowerStatsSnapshot

__all__ = [
    "PowerReading",
    "PowerSource",
    "DummySource",
    "SysfsPowerSource",
    "select_default_source",
    "PowerSampler",
    "PowerStats",
    "PowerStatsFrame",
    "PowerStatsSnapshot",
]
