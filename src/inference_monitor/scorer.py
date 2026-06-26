"""Deployment readiness scorer for inference benchmarks.

Computes a weighted composite score (0-100) from four dimensions:
FPS, latency, thermal, and power.  Each sub-score is independently
clamped to [0, 100] before weighting.

Formula (from ``spec/inference-integration.md`` section 5.1)::

    total = fps_score*0.3 + latency_score*0.3 + thermal_score*0.2 + power_score*0.2

    fps_score      = min(100, fps / target_fps * 100)
    latency_score  = max(0, 100 - (p95_ms - target_ms) * 10)
    thermal_score  = max(0, 100 - max(0, peak_temp - 70) * 5)
    power_score    = max(0, 100 - max(0, avg_power - budget_watt) * 10)

Python 3.8+ compatible.  No external dependencies.
"""

from __future__ import annotations

from typing import List, Optional

from .results import DeploymentScore


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* into [lo, hi]."""
    return max(lo, min(hi, value))


def _fps_score(fps: float, target_fps: float) -> float:
    if target_fps <= 0:
        return 0.0
    return _clamp(fps / target_fps * 100.0)


def _latency_score(p95_ms: float, target_ms: float) -> float:
    return _clamp(100.0 - (p95_ms - target_ms) * 10.0)


def _thermal_score(peak_temp: float) -> float:
    return _clamp(100.0 - max(0.0, peak_temp - 70.0) * 5.0)


def _power_score(avg_power: float, budget_watt: float) -> float:
    return _clamp(100.0 - max(0.0, avg_power - budget_watt) * 10.0)


def _verdict(total: int) -> str:
    if total >= 80:
        return "ready"
    if total >= 50:
        return "marginal"
    return "not_ready"


def _identify_bottlenecks(
    fps_s: float,
    lat_s: float,
    thr_s: float,
    pwr_s: float,
    fps: float,
    target_fps: float,
    p95_ms: float,
    target_ms: float,
    peak_temp: float,
    avg_power: float,
    budget_watt: float,
) -> List[str]:
    """Return a list of human-readable bottleneck descriptions."""
    bottlenecks: List[str] = []
    if fps_s < 60:
        bottlenecks.append(
            f"FPS below target: {fps:.1f} < {target_fps:.1f}"
        )
    if lat_s < 60:
        bottlenecks.append(
            f"P95 latency above target: {p95_ms:.1f}ms > {target_ms:.1f}ms"
        )
    if thr_s < 60:
        bottlenecks.append(
            f"Temperature too high: {peak_temp:.1f}C (safe limit 70C)"
        )
    if pwr_s < 60:
        bottlenecks.append(
            f"Power over budget: {avg_power:.1f}W > {budget_watt:.1f}W"
        )
    return bottlenecks


class DeploymentScorer:
    """Score a benchmark run against deployment targets."""

    def score(
        self,
        fps: float,
        target_fps: float,
        p95_ms: float,
        target_ms: float,
        peak_temp: float,
        avg_power: float,
        budget_watt: float,
    ) -> DeploymentScore:
        """Compute the composite deployment score.

        All temperature values are in Celsius, power in Watts, latency
        in milliseconds.

        Returns:
            A :class:`DeploymentScore` with individual sub-scores,
            composite total, verdict, and identified bottlenecks.
        """
        fps_s = _fps_score(fps, target_fps)
        lat_s = _latency_score(p95_ms, target_ms)
        thr_s = _thermal_score(peak_temp)
        pwr_s = _power_score(avg_power, budget_watt)

        raw_total = fps_s * 0.3 + lat_s * 0.3 + thr_s * 0.2 + pwr_s * 0.2
        total = int(round(_clamp(raw_total)))

        bottlenecks = _identify_bottlenecks(
            fps_s, lat_s, thr_s, pwr_s,
            fps, target_fps, p95_ms, target_ms, peak_temp, avg_power, budget_watt,
        )

        return DeploymentScore(
            total=total,
            fps_score=int(round(fps_s)),
            latency_score=int(round(lat_s)),
            thermal_score=int(round(thr_s)),
            power_score=int(round(pwr_s)),
            verdict=_verdict(total),
            bottlenecks=bottlenecks,
        )
