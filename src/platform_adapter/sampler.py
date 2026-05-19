"""Non-busy-wait platform metrics sampler.

Mirrors `power_monitor.PowerSampler`: drift-free scheduling via
`time.monotonic()` + `time.sleep()`. The same pattern is duplicated here
on purpose — these two samplers run on different cadences and the small
amount of repeated code keeps the modules independently swappable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Event, Lock, Thread
from typing import Callable, Optional

from .probe import PlatformProbe, RawMetrics

SampleCallback = Callable[[RawMetrics], None]


@dataclass
class SamplerState:
    sample_count: int = 0
    last_jitter_ms: float = 0.0


class PlatformSampler:
    """Periodic sampler for `PlatformProbe`.

    Args:
        probe: Probe implementation.
        interval_ms: Sampling interval in milliseconds.
        on_sample: Optional callback invoked for each reading.
    """

    def __init__(
        self,
        probe: PlatformProbe,
        interval_ms: int = 1000,
        on_sample: Optional[SampleCallback] = None,
    ) -> None:
        if interval_ms <= 0:
            raise ValueError("interval_ms must be > 0")
        self.probe = probe
        self.interval_ms = interval_ms
        self.on_sample = on_sample

        self._state = SamplerState()
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._lock = Lock()
        self._last_tick: Optional[float] = None

    @property
    def sample_count(self) -> int:
        with self._lock:
            return self._state.sample_count

    @property
    def last_jitter_ms(self) -> float:
        with self._lock:
            return self._state.last_jitter_ms

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run_loop, name="platform-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.probe.close()

    def poll_once(self) -> RawMetrics:
        reading = self.probe.read_metrics()
        with self._lock:
            self._state.sample_count += 1
        if self.on_sample is not None:
            self.on_sample(reading)
        return reading

    def _run_loop(self) -> None:
        next_tick = time.monotonic()
        self._last_tick = next_tick

        while not self._stop_event.is_set():
            now = time.monotonic()
            sleep_s = max(0.0, next_tick - now)
            if sleep_s > 0:
                time.sleep(sleep_s)

            tick = time.monotonic()
            last_tick = self._last_tick if self._last_tick is not None else tick
            jitter_ms = abs((tick - last_tick) * 1000.0 - self.interval_ms)
            self._last_tick = tick

            reading = self.probe.read_metrics()
            with self._lock:
                self._state.sample_count += 1
                self._state.last_jitter_ms = jitter_ms

            if self.on_sample is not None:
                self.on_sample(reading)

            next_tick += self.interval_ms / 1000.0
