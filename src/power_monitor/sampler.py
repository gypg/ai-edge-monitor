"""Non-busy-wait power sampling loop.

This sampler uses time.monotonic() + sleep() scheduling to avoid busy waiting.
It can run in background thread mode or via explicit poll_once() calls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Event, Lock, Thread
from typing import Callable, Optional

from .source import PowerReading, PowerSource

SampleCallback = Callable[[PowerReading], None]


@dataclass
class SamplerState:
    sample_count: int = 0
    last_jitter_ms: float = 0.0


class PowerSampler:
    """Periodic sampler for PowerSource.

    Args:
        source: Sampling source implementation.
        interval_ms: Sampling interval in milliseconds.
        timeout_ms: Per-read timeout hint passed to source.
        on_sample: Optional callback invoked for each reading.
    """

    def __init__(
        self,
        source: PowerSource,
        interval_ms: int = 1000,
        timeout_ms: int = 50,
        on_sample: Optional[SampleCallback] = None,
    ) -> None:
        if interval_ms <= 0:
            raise ValueError("interval_ms must be > 0")
        self.source = source
        self.interval_ms = interval_ms
        self.timeout_ms = timeout_ms
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
        """Start background sampling thread if not already running."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run_loop, name="power-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop background sampling thread and close source."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.source.close()

    def poll_once(self) -> PowerReading:
        """Collect one reading synchronously."""
        reading = self.source.read_once(self.timeout_ms)
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

            reading = self.source.read_once(self.timeout_ms)
            with self._lock:
                self._state.sample_count += 1
                self._state.last_jitter_ms = jitter_ms

            if self.on_sample is not None:
                self.on_sample(reading)

            next_tick += self.interval_ms / 1000.0
