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

from typing import Tuple

from .nvidia_smi_probe import NvidiaSmiProbe
from .probe import CompositeProbe, DummyProbe, PlatformCaps, PlatformProbe, RawMetrics
from .procfs_probe import ProcfsProbe
from .psutil_probe import PsutilProbe
from .sampler import PlatformSampler


def select_default_probe(prefer: Tuple[str, ...] = ("procfs", "psutil")) -> PlatformProbe:
    """Return the best available probe for this host.

    If an nvidia-smi GPU probe is available, it is automatically composed
    with the primary (CPU / memory) probe so GPU metrics appear alongside
    CPU / memory readings without requiring manual configuration.
    """
    candidates = _resolve_probes(prefer)
    primary: PlatformProbe = DummyProbe()
    for probe in candidates:
        if probe.is_available():
            primary = probe
            break
    gpu = NvidiaSmiProbe()
    if gpu.is_available():
        return CompositeProbe([primary, gpu])
    return primary


def _resolve_probes(names: Tuple[str, ...]) -> list:
    mapping = {
        "nvidia-smi": NvidiaSmiProbe,
        "procfs": ProcfsProbe,
        "psutil": PsutilProbe,
    }
    return [mapping[n]() for n in names if n in mapping]


__all__ = [
    "PlatformProbe",
    "PlatformCaps",
    "RawMetrics",
    "CompositeProbe",
    "DummyProbe",
    "NvidiaSmiProbe",
    "ProcfsProbe",
    "PsutilProbe",
    "PlatformSampler",
    "select_default_probe",
]
