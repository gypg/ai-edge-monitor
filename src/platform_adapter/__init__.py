"""platform_adapter — unified CPU/GPU/memory/temperature probes.

Public API:
    PlatformProbe   — abstract probe contract
    PlatformCaps    — capability summary
    RawMetrics      — standardized cross-probe reading
    DummyProbe      — synthetic probe (tests / dev hosts)
    ProcfsProbe     — Linux /proc + /sys/class/thermal
    PsutilProbe     — cross-platform fallback (psutil required)
    NvidiaSmiProbe  — NVIDIA GPU probe
    EmbeddedProbe   — Jetson / Raspberry Pi 专用探测器
    PlatformSampler — non-busy-wait periodic sampler
    select_default_probe(prefer) — pick the first available probe

Power collection lives in `power_monitor`, not here. See
`docs/changelog/add-power-monitor.md` for the v2 split.
"""

from __future__ import annotations

from typing import Tuple

from .embedded_probe import EmbeddedProbe
from .nvidia_smi_probe import NvidiaSmiProbe
from .probe import CompositeProbe, DummyProbe, PlatformCaps, PlatformProbe, RawMetrics
from .procfs_probe import ProcfsProbe
from .psutil_probe import PsutilProbe
from .sampler import PlatformSampler


def select_default_probe(prefer: Tuple[str, ...] = ("embedded", "procfs", "psutil")) -> PlatformProbe:
    """Return the best available probe for this host.

    If an nvidia-smi GPU probe is available, it is automatically composed
    with the primary (CPU / memory) probe so GPU metrics appear alongside
    CPU / memory readings without requiring manual configuration.
    
    For embedded devices (Jetson/Raspberry Pi), the EmbeddedProbe is used
    as it provides device-specific optimizations.
    """
    candidates = _resolve_probes(prefer)
    primary: PlatformProbe = DummyProbe()
    for probe in candidates:
        if probe.is_available():
            primary = probe
            break
    
    # 对于嵌入式设备，EmbeddedProbe 已经包含了 GPU 支持
    if isinstance(primary, EmbeddedProbe):
        return primary
    
    # 对于其他设备，尝试组合 NVIDIA GPU 探测器
    gpu = NvidiaSmiProbe()
    if gpu.is_available():
        return CompositeProbe([primary, gpu])
    return primary


def _resolve_probes(names: Tuple[str, ...]) -> list:
    mapping = {
        "embedded": EmbeddedProbe,
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
    "EmbeddedProbe",
    "NvidiaSmiProbe",
    "ProcfsProbe",
    "PsutilProbe",
    "PlatformSampler",
    "select_default_probe",
]
