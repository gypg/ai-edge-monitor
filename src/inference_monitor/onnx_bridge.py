"""ONNX Runtime profiling bridge.

Wraps ORT session profiling with graceful fallback when onnxruntime is
not installed.  Parses the ORT JSON profiling output to extract per-operator
timing as ``LayerProfile`` records.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import onnxruntime as ort  # type: ignore[import-untyped]

    HAS_ORT = True
except ImportError:
    HAS_ORT = False


@dataclass
class LayerProfile:
    """Per-operator timing extracted from ORT profiling JSON."""

    name: str
    avg_time_ms: float
    calls: int


def _parse_ort_profiling_json(data: Dict[str, Any]) -> List[LayerProfile]:
    """Convert raw ORT profiling JSON into a list of ``LayerProfile``.

    ORT emits a Chrome-trace-style JSON with a ``[]``-array under the key
    ``"traceEvents"``.  Each event has ``cat``, ``name``, ``dur`` (microseconds),
    etc.  Operator-level events have ``cat == "Node"``.
    """
    events = data.get("traceEvents", [])
    op_events: Dict[str, List[float]] = {}

    for event in events:
        cat = event.get("cat", "")
        if cat != "Node":
            continue
        name = event.get("name", "unknown")
        dur_us = event.get("dur", 0.0)
        dur_ms = dur_us / 1000.0
        op_events.setdefault(name, []).append(dur_ms)

    profiles: List[LayerProfile] = []
    for name, durations in op_events.items():
        profiles.append(
            LayerProfile(
                name=name,
                avg_time_ms=sum(durations) / len(durations),
                calls=len(durations),
            )
        )
    # Sort by total time descending so the hottest operators surface first.
    profiles.sort(key=lambda p: p.avg_time_ms * p.calls, reverse=True)
    return profiles


class OnnxProfiler:
    """Thin wrapper around ONNX Runtime's built-in session profiling.

    Usage::

        profiler = OnnxProfiler()
        profiler.start_profiling(session)
        session.run(...)
        result = profiler.stop_profiling()

    When *onnxruntime* is not installed every public method degrades to a
    no-op and logs a WARNING on first use.
    """

    def __init__(self) -> None:
        self._session: Any = None
        self._original_options: Any = None
        self._profiling_file: Optional[str] = None
        self._warned = False

    def _warn_unavailable(self) -> None:
        if not self._warned:
            logger.warning(
                "onnxruntime not available, ONNX profiling disabled"
            )
            self._warned = True

    def start_profiling(self, session: Any) -> None:
        """Enable profiling on the given ORT *session*.

        If *onnxruntime* is unavailable the call is silently ignored (after
        emitting one warning).
        """
        if not HAS_ORT:
            self._warn_unavailable()
            return

        so = session.get_session_options()
        self._session = session
        # Enable profiling on the session options copy.  ORT >= 1.10
        # exposes ``enable_profiling`` on ``SessionOptions``.
        so.enable_profiling = True
        so.profile_file_prefix = os.path.join(
            tempfile.gettempdir(), "ort_profile"
        )

    def stop_profiling(self) -> Dict[str, Any]:
        """Disable profiling and return the parsed profiling dict.

        Returns a dictionary with keys ``"layers"`` (``List[LayerProfile]``)
        and ``"raw"`` (the unprocessed JSON).  When profiling was not started
        or *onnxruntime* is missing, returns ``{"layers": [], "raw": {}}``.
        """
        if not HAS_ORT:
            self._warn_unavailable()
            return {"layers": [], "raw": {}}

        if self._session is None:
            return {"layers": [], "raw": {}}

        profile_path = self._session.end_profiling()
        self._session = None

        return self.parse_profile(profile_path)

    @staticmethod
    def parse_profile(profile_path: str) -> Dict[str, Any]:
        """Read an ORT profiling JSON file and return parsed results.

        Returns ``{"layers": [...], "raw": {...}}``.
        """
        try:
            with open(profile_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read ORT profile %s: %s", profile_path, exc)
            return {"layers": [], "raw": {}}

        layers = _parse_ort_profiling_json(data)
        return {"layers": layers, "raw": data}
