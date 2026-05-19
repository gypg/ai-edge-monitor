"""Workload scenarios for DummyProbe / DummySource.

A scenario is a small object that, given a wall-clock time `t` (seconds
since the scenario started), returns synthetic readings. Concrete
scenarios encode load shapes that match the project's PRD examples:

    - IdleScenario:       CPU ~5%, power ~2W
    - InferenceScenario:  CPU ~75%, power ~8W, periodic spikes
    - ThrottledScenario:  CPU ramps to 95%, then drops to ~60% after
                          a thermal trip; power follows.

Public API:
    Scenario              — abstract base class
    IdleScenario, InferenceScenario, ThrottledScenario
    make_scenario(name)   — factory, raises KeyError on unknown name

Scenarios are *deterministic per (t, seed)*, so reports are reproducible.
"""

from __future__ import annotations

import math
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional, Type


@dataclass
class ScenarioPoint:
    """A single (cpu, mem, temp, power) tuple produced by a scenario."""

    cpu_percent: float
    mem_used_mb: float
    temperature_c: Optional[float]
    power_watt: float


class Scenario(ABC):
    """Abstract scenario.

    Concrete subclasses implement `_sample(t)` returning a ScenarioPoint
    for elapsed seconds `t`. The base class adds:
      - a per-call deterministic noise channel keyed on `seed`;
      - lazy start-time anchoring (the first call sets t=0);
      - an optional `freeze_time` hook for tests.
    """

    name: str = "base"

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed
        self._t0: Optional[float] = None
        self._rng = random.Random(seed)

    def reset(self) -> None:
        self._t0 = None
        self._rng = random.Random(self._seed)

    def now(self) -> float:
        if self._t0 is None:
            self._t0 = time.monotonic()
            return 0.0
        return time.monotonic() - self._t0

    def jitter(self, amplitude: float) -> float:
        if amplitude <= 0:
            return 0.0
        return self._rng.uniform(-amplitude, amplitude)

    def sample(self, t: Optional[float] = None) -> ScenarioPoint:
        if t is None:
            t = self.now()
        return self._sample(t)

    @abstractmethod
    def _sample(self, t: float) -> ScenarioPoint:
        ...


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class IdleScenario(Scenario):
    """Low-load idle: CPU ~5%, mem stable, power ~2W."""

    name = "idle"

    def _sample(self, t: float) -> ScenarioPoint:
        cpu = _clamp(5.0 + self.jitter(1.0), 0.0, 100.0)
        mem = 400.0 + self.jitter(15.0)
        temp = 38.0 + self.jitter(0.8)
        power = max(0.1, 2.0 + self.jitter(0.15))
        return ScenarioPoint(cpu, mem, temp, power)


class InferenceScenario(Scenario):
    """Steady inference load with periodic spikes.

    Models a model serving loop that hits ~75% CPU on average with a
    short burst every ~12 seconds (e.g. a periodic batch flush). Power
    tracks CPU with a small lag and amplitude.
    """

    name = "inference"

    def _sample(self, t: float) -> ScenarioPoint:
        spike = 18.0 if (int(t) % 12 == 0 and t > 0) else 0.0
        cpu = _clamp(75.0 + spike + self.jitter(3.0), 0.0, 100.0)
        mem = 1500.0 + 50.0 * math.sin(t / 6.0) + self.jitter(20.0)
        temp = 60.0 + spike * 0.15 + self.jitter(1.2)
        # Power leads CPU by ~1s; approximate as cpu/100 * 8 + small base.
        power = max(0.1, 8.0 + (spike * 0.05) + self.jitter(0.4))
        return ScenarioPoint(cpu, mem, temp, power)


class ThrottledScenario(Scenario):
    """Thermal-throttled ramp.

    Phases (each 20s for a 60s run):
        0-20s : CPU ramps from 50% to 95%, power follows up to ~9W.
        20-40s: temperature crosses thermal trip; CPU dropped to ~60%,
                power drops to ~5W. Brief oscillation as governor settles.
        40-60s: stable post-throttle plateau at 60% / 5W.
    """

    name = "throttled"

    RAMP_END = 20.0
    THROTTLE_END = 40.0

    def _sample(self, t: float) -> ScenarioPoint:
        if t < self.RAMP_END:
            ramp_pct = t / self.RAMP_END
            cpu = 50.0 + ramp_pct * 45.0
            power = 5.0 + ramp_pct * 4.0
            temp = 50.0 + ramp_pct * 30.0
        elif t < self.THROTTLE_END:
            # Brief oscillation while the governor settles after the trip.
            phase = (t - self.RAMP_END) / (self.THROTTLE_END - self.RAMP_END)
            decay = math.exp(-phase * 3.0)
            oscillation = 5.0 * decay * math.sin((t - self.RAMP_END) * 4.0)
            cpu = 60.0 + oscillation
            power = 5.0 + oscillation * 0.2
            temp = 80.0 - phase * 8.0
        else:
            cpu = 60.0
            power = 5.0
            temp = 72.0

        cpu = _clamp(cpu + self.jitter(1.5), 0.0, 100.0)
        power = max(0.1, power + self.jitter(0.15))
        temp_v = temp + self.jitter(0.6)
        mem = 900.0 + self.jitter(25.0)
        return ScenarioPoint(cpu, mem, temp_v, power)


_REGISTRY: Dict[str, Type[Scenario]] = {
    "idle": IdleScenario,
    "inference": InferenceScenario,
    "throttled": ThrottledScenario,
}


def make_scenario(name: str, seed: int = 0) -> Scenario:
    """Factory. `name` is one of "idle", "inference", "throttled"."""
    try:
        cls = _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown scenario {name!r}; expected one of {sorted(_REGISTRY)}") from exc
    return cls(seed=seed)


__all__ = [
    "Scenario",
    "ScenarioPoint",
    "IdleScenario",
    "InferenceScenario",
    "ThrottledScenario",
    "make_scenario",
]
