"""TensorRT profiler bridge — captures per-layer execution times.

When the ``tensorrt`` package is not installed the module degrades to a
no-op so that callers never need a ``try/except`` around imports.

Design notes (spec §3):
- Implements ``trt.IProfiler`` pattern when TensorRT is available.
- Records each layer's name, cumulative time, and call count.
- ``HAS_TENSORRT`` is the single flag consumers should check.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional TensorRT import
# ---------------------------------------------------------------------------

try:
    import tensorrt as trt  # type: ignore

    HAS_TENSORRT = True
except ImportError:
    HAS_TENSORRT = False

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayerProfile:
    """Immutable snapshot of a single TensorRT layer's execution stats."""

    name: str
    avg_time_ms: float
    calls: int


@dataclass
class _LayerAccumulator:
    """Internal mutable accumulator — not part of the public API."""

    total_time_ms: float = 0.0
    calls: int = 0


# ---------------------------------------------------------------------------
# TensorRTProfiler
# ---------------------------------------------------------------------------


class TensorRTProfiler:
    """Capture per-layer execution times from a TensorRT engine.

    When TensorRT is available this class is compatible with the
    ``trt.IProfiler`` callback protocol.  When it is not, every public
    method is a safe no-op.
    """

    def __init__(self) -> None:
        self._layers: Dict[str, _LayerAccumulator] = {}
        self._warned_no_trt: bool = False

    # ------------------------------------------------------------------
    # trt.IProfiler-compatible callback
    # ------------------------------------------------------------------

    def report_layer_time(self, layer_name: str, ms: float) -> None:
        """Record the execution time for *layer_name*.

        TensorRT calls this once per layer per inference when the
        profiler is registered via ``engine.create_execution_context()``
        and ``context.profiler = self``.
        """
        if not HAS_TENSORRT and not self._warned_no_trt:
            logger.warning(
                "TensorRT not available, layer profiling is running in no-op mode"
            )
            self._warned_no_trt = True

        acc = self._layers.get(layer_name)
        if acc is None:
            acc = _LayerAccumulator()
            self._layers[layer_name] = acc
        acc.total_time_ms += ms
        acc.calls += 1

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_layer_profiles(self) -> List[LayerProfile]:
        """Return an immutable list of per-layer profiles sorted by name."""
        profiles: List[LayerProfile] = []
        for name in sorted(self._layers):
            acc = self._layers[name]
            avg = acc.total_time_ms / acc.calls if acc.calls else 0.0
            profiles.append(LayerProfile(name=name, avg_time_ms=avg, calls=acc.calls))
        return profiles

    def get_total_time_ms(self) -> float:
        """Return the sum of all recorded layer execution times (ms)."""
        return sum(acc.total_time_ms for acc in self._layers.values())

    def reset(self) -> None:
        """Clear all recorded layer data."""
        self._layers.clear()
