from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LeakAlert:
    """Alert emitted when a memory leak pattern is detected."""

    target_pid: int
    target_name: str
    r_squared: float
    slope_mb_per_sec: float
    estimated_time_to_oom: Optional[float]
    window_start_ms: int
    window_end_ms: int
    sample_count: int
