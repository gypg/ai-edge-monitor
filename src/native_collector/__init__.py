"""Native C++ collector with Python fallback.

When the compiled C++ extension (_native_collector) is available, uses it
for ~10x faster /proc reads. Otherwise falls back to Python ProcfsProbe.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from _native_collector import NativeProbe, NeonStats

    HAS_NATIVE = True
except ImportError:
    HAS_NATIVE = False
    NativeProbe = None
    NeonStats = None


def select_probe(force_native: bool = False) -> Any:
    """Select the best available probe: Native > Procfs > Psutil > Dummy.

    Parameters
    ----------
    force_native:
        If True, raise ImportError when native module is unavailable.

    Returns
    -------
    A probe object with read_metrics() -> RawMetrics interface.
    """
    if force_native:
        if not HAS_NATIVE:
            raise ImportError(
                "Native collector not available. Build with: "
                "cd native && cmake -B build && cmake --build build"
            )
        return NativeProbe()

    if HAS_NATIVE:
        logger.info("Using native C++ collector")
        return NativeProbe()

    # Fallback to Python implementation
    logger.info("Native collector unavailable, falling back to Python probe")
    try:
        from platform_adapter import select_default_probe

        return select_default_probe()
    except ImportError:
        from platform_adapter import DummyProbe

        return DummyProbe()
