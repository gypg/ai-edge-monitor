"""platform_adapter — unified CPU/GPU/memory/temperature probes.

Public API:
    PlatformProbe   — abstract probe contract
    PlatformCaps    — capability summary
    RawMetrics      — standardized cross-probe reading
    DummyProbe      — synthetic probe (tests / dev hosts)
    ProcfsProbe     — Linux /proc + /sys/class/thermal
    PsutilProbe     — cross-platform fallback (psutil required)
    PlatformSampler — non-busy-wait periodic sampler
    select_default_probe(prefer) — pick the first available probe

Power collection lives in `power_monitor`, not here. See
`docs/changelog/add-power-monitor.md` for the v2 split.
"""

from __future__ import annotations

from typing import List, Tuple

from .probe import DummyProbe, PlatformCaps, PlatformProbe, RawMetrics
from .procfs_probe import ProcfsProbe
from .psutil_probe import PsutilProbe
from .sampler import PlatformSampler


def select_default_probe(prefer: Tuple[str, ...] = ("procfs", "psutil")) -> PlatformProbe:
    """Return the first available probe from `prefer`, falling back to DummyProbe."""
    candidates: List[PlatformProbe] = []
    for name in prefer:
        if name == "procfs":
            candidates.append(ProcfsProbe())
        elif name == "psutil":
            candidates.append(PsutilProbe())
        # TODO: register Jetson, NVML, vcgencmd probes here.
    for probe in candidates:
        if probe.is_available():
            return probe
    return DummyProbe()


__all__ = [
    "PlatformProbe",
    "PlatformCaps",
    "RawMetrics",
    "DummyProbe",
    "ProcfsProbe",
    "PsutilProbe",
    "PlatformSampler",
    "select_default_probe",
]
