"""runtime_guardian — self-overhead watchdog with degrade hooks.

The guardian runs in a background thread, samples this process's RSS
and CPU% every `interval_sec` (default 5s), and calls user-supplied
`on_degrade` / `on_recover` hooks when thresholds are crossed. It uses
hysteresis (separate "high" and "low" thresholds) so a process bouncing
right around the limit doesn't toggle states constantly.

When `psutil` is unavailable, the guardian gracefully self-disables:
`get_health()` returns `{"enabled": False, ...}`, no callbacks fire, and
a one-time WARNING is logged on `start()`. This matches the same
"degrade gracefully if psutil missing" pattern used by the platform
adapter and the baseline tests.

Test-mode injection:
    `inject_test_load(cpu_percent=..., rss_mb=...)` makes the next
    sample return the injected values *instead of* the real psutil
    readings. Used by tests/integration to drive degrade/recover paths
    deterministically without spawning real CPU load.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

LOG = logging.getLogger("runtime_guardian")

try:
    import psutil

    _PSUTIL_OK = True
except ModuleNotFoundError:
    psutil = None
    _PSUTIL_OK = False


@dataclass
class GuardianConfig:
    """Thresholds + cadence.

    `cpu_percent_high/low` and `rss_mb_high/low` define hysteresis
    bands: enter degraded when ANY high threshold is crossed; recover
    only when ALL metrics fall back below their low threshold for one
    consecutive sample.
    """

    interval_sec: float = 5.0
    cpu_percent_high: float = 3.0
    cpu_percent_low: float = 2.0
    rss_mb_high: float = 50.0
    rss_mb_low: float = 40.0
    test_mode: bool = False


DegradeFn = Callable[[Dict[str, Any]], None]
RecoverFn = Callable[[Dict[str, Any]], None]


class RuntimeGuardian:
    """Self-overhead watchdog with hysteresis."""

    def __init__(
        self,
        config: Optional[GuardianConfig] = None,
        on_degrade: Optional[DegradeFn] = None,
        on_recover: Optional[RecoverFn] = None,
    ) -> None:
        self.config = config or GuardianConfig()
        self._on_degrade = on_degrade
        self._on_recover = on_recover

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._enabled = _PSUTIL_OK
        self._last_cpu: float = 0.0
        self._last_rss: float = 0.0
        self._sample_count = 0
        self._degraded = False
        self._degrade_count = 0
        self._recover_count = 0
        self._injected_cpu: Optional[float] = None
        self._injected_rss: Optional[float] = None
        self._proc = None

        if self._enabled:
            self._proc = psutil.Process(os.getpid())
            try:
                self._proc.cpu_percent(interval=None)
            except Exception:
                pass

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def is_degraded(self) -> bool:
        return self._degraded

    def get_health(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "degraded": self._degraded,
                "last_cpu_percent": self._last_cpu,
                "last_rss_mb": self._last_rss,
                "sample_count": self._sample_count,
                "degrade_count": self._degrade_count,
                "recover_count": self._recover_count,
            }

    def inject_test_load(
        self, cpu_percent: Optional[float] = None, rss_mb: Optional[float] = None
    ) -> None:
        """Override the next sample with synthetic values.

        Either argument may be left as None to keep the real reading
        for that metric. Effect persists until cleared with
        `clear_injection()` or replaced with another inject call.
        """
        if not self.config.test_mode and not _PSUTIL_OK:
            # In production-with-psutil-missing mode we still allow
            # injection so tests can drive the logic.
            pass
        with self._lock:
            self._injected_cpu = cpu_percent
            self._injected_rss = rss_mb
            self._enabled = True

    def clear_injection(self) -> None:
        with self._lock:
            self._injected_cpu = None
            self._injected_rss = None
            if not _PSUTIL_OK and not self.config.test_mode:
                self._enabled = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not self._enabled and not self.config.test_mode:
            LOG.warning("runtime_guardian: psutil unavailable; self-protection disabled")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="runtime-guardian",
            daemon=True,
        )
        self._thread.start()

    def stop(self, join_timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=join_timeout)

    def check_now(self) -> Dict[str, Any]:
        """Take one immediate sample and apply degrade/recover logic."""
        cpu_pct = 0.0
        rss_mb = 0.0
        if self._proc is not None:
            try:
                cpu_pct = float(self._proc.cpu_percent(interval=None))
            except Exception:
                cpu_pct = 0.0
            try:
                rss_mb = self._proc.memory_info().rss / (1024 * 1024)
            except Exception:
                rss_mb = 0.0

        with self._lock:
            if self._injected_cpu is not None:
                cpu_pct = float(self._injected_cpu)
            if self._injected_rss is not None:
                rss_mb = float(self._injected_rss)
            self._last_cpu = cpu_pct
            self._last_rss = rss_mb
            self._sample_count += 1

            crossed_high = (
                cpu_pct > self.config.cpu_percent_high or rss_mb > self.config.rss_mb_high
            )
            below_low = cpu_pct < self.config.cpu_percent_low and rss_mb < self.config.rss_mb_low

            transition: Optional[str] = None
            if not self._degraded and crossed_high:
                self._degraded = True
                self._degrade_count += 1
                transition = "degrade"
            elif self._degraded and below_low:
                self._degraded = False
                self._recover_count += 1
                transition = "recover"

            health = {
                "cpu_percent": cpu_pct,
                "rss_mb": rss_mb,
                "degraded": self._degraded,
                "transition": transition,
            }

        if transition == "degrade" and self._on_degrade is not None:
            try:
                self._on_degrade(health)
            except Exception as exc:
                LOG.error("on_degrade callback failed: %s", exc)
        elif transition == "recover" and self._on_recover is not None:
            try:
                self._on_recover(health)
            except Exception as exc:
                LOG.error("on_recover callback failed: %s", exc)

        return health

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.check_now()
            except Exception as exc:
                LOG.error("guardian sample failed: %s", exc)
            self._stop_event.wait(timeout=self.config.interval_sec)
