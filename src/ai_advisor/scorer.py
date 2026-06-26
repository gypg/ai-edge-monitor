"""Deployment readiness scorer — evaluates whether a device meets deployment targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class DeploymentAssessment:
    """Result of a deployment readiness evaluation."""

    ready: bool
    score: int  # 0-100
    fps_headroom: float  # (target - actual) / target
    latency_headroom: float  # (target - p95) / target
    thermal_headroom: float  # (limit - peak) / limit
    power_headroom: float  # (budget - avg) / budget
    blocking_issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* between *lo* and *hi*."""
    return max(lo, min(hi, value))


def _safe_float(mapping: Dict[str, Any], key: str, default: float = 0.0) -> float:
    """Extract a numeric value from *mapping*, falling back to *default*."""
    val = mapping.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def assess_deployment_readiness(
    summary: Dict[str, Any],
    target_fps: float,
    target_latency_ms: float,
    power_budget_watt: float,
    thermal_limit_c: float = 80.0,
) -> DeploymentAssessment:
    """Evaluate whether current device metrics meet deployment requirements.

    Parameters
    ----------
    summary:
        Aggregated monitoring summary.  Expected keys (all optional)::

            fps_avg        — average frames-per-second
            latency_p95_ms — 95th-percentile latency in milliseconds
            temp_max_c     — peak temperature in degrees Celsius
            power_avg_watt — average power draw in watts

    target_fps:
        Minimum acceptable FPS.
    target_latency_ms:
        Maximum acceptable P95 latency in ms.
    power_budget_watt:
        Maximum average power in watts.
    thermal_limit_c:
        Hard thermal ceiling in degrees Celsius (default 80).

    Returns
    -------
    DeploymentAssessment
    """
    # --- Early exit: empty / all-missing summary → score 0 -----------------
    _EXPECTED_KEYS = ("fps_avg", "latency_p95_ms", "temp_max_c", "power_avg_watt")
    has_any_data = any(summary.get(k) is not None for k in _EXPECTED_KEYS)

    if not has_any_data:
        return DeploymentAssessment(
            ready=False,
            score=0,
            fps_headroom=0.0,
            latency_headroom=0.0,
            thermal_headroom=0.0,
            power_headroom=0.0,
            blocking_issues=["No monitoring data available"],
            warnings=[],
        )

    actual_fps = _safe_float(summary, "fps_avg")
    p95_ms = _safe_float(summary, "latency_p95_ms")
    peak_temp = _safe_float(summary, "temp_max_c")
    avg_power = _safe_float(summary, "power_avg_watt")

    # --- Headroom calculations (fraction, not percentage) -------------------
    fps_headroom = (target_fps - actual_fps) / target_fps if target_fps > 0 else 0.0
    latency_headroom = (
        (target_latency_ms - p95_ms) / target_latency_ms if target_latency_ms > 0 else 0.0
    )
    thermal_headroom = (
        (thermal_limit_c - peak_temp) / thermal_limit_c if thermal_limit_c > 0 else 0.0
    )
    power_headroom = (
        (power_budget_watt - avg_power) / power_budget_watt if power_budget_watt > 0 else 0.0
    )

    # --- Sub-scores ---------------------------------------------------------
    fps_score = _clamp(actual_fps / target_fps * 100) if target_fps > 0 else 0.0
    latency_score = _clamp(max(0.0, 100 - max(0.0, p95_ms - target_latency_ms) * 10))
    thermal_score = _clamp(max(0.0, 100 - max(0.0, peak_temp - 70) * 5))
    power_score = _clamp(max(0.0, 100 - max(0.0, avg_power - power_budget_watt) * 10))

    total = fps_score * 0.3 + latency_score * 0.3 + thermal_score * 0.2 + power_score * 0.2

    # --- Blocking issues & warnings ----------------------------------------
    blocking_issues: List[str] = []
    warnings: List[str] = []

    if fps_score < 50:
        blocking_issues.append(
            f"FPS critically low: {actual_fps:.1f} fps "
            f"(target {target_fps:.0f}, score {fps_score:.0f})"
        )
    elif fps_score < 70:
        warnings.append(
            f"FPS below target: {actual_fps:.1f} fps "
            f"(target {target_fps:.0f}, score {fps_score:.0f})"
        )

    if thermal_score < 30:
        blocking_issues.append(
            f"Temperature critical: {peak_temp:.1f} C "
            f"(limit {thermal_limit_c:.0f} C, score {thermal_score:.0f})"
        )
    elif thermal_score < 60:
        warnings.append(
            f"Temperature elevated: {peak_temp:.1f} C "
            f"(limit {thermal_limit_c:.0f} C, score {thermal_score:.0f})"
        )

    if power_score < 50:
        warnings.append(
            f"Power budget exceeded: {avg_power:.1f} W "
            f"(budget {power_budget_watt:.0f} W, score {power_score:.0f})"
        )

    if latency_score < 50:
        warnings.append(
            f"Latency too high: P95 {p95_ms:.1f} ms "
            f"(target {target_latency_ms:.0f} ms, score {latency_score:.0f})"
        )

    # --- Final verdict ------------------------------------------------------
    overall_score = int(round(total))
    ready = overall_score >= 70 and len(blocking_issues) == 0

    return DeploymentAssessment(
        ready=ready,
        score=overall_score,
        fps_headroom=round(fps_headroom, 4),
        latency_headroom=round(latency_headroom, 4),
        thermal_headroom=round(thermal_headroom, 4),
        power_headroom=round(power_headroom, 4),
        blocking_issues=blocking_issues,
        warnings=warnings,
    )
