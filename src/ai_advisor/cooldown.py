"""Cooldown tracker — prevents the same rule from firing too frequently."""

import time
from typing import Dict


class CooldownTracker:
    """Per-rule cooldown using monotonic clock."""

    def __init__(self) -> None:
        self._last_fired: Dict[str, float] = {}

    def should_fire(self, rule_name: str, cooldown_sec: float = 60.0) -> bool:
        """Return True if *rule_name* is outside its cooldown window."""
        now = time.monotonic()
        last = self._last_fired.get(rule_name, 0.0)
        if now - last < cooldown_sec:
            return False
        self._last_fired[rule_name] = now
        return True

    def reset(self) -> None:
        """Clear all cooldown state."""
        self._last_fired.clear()
