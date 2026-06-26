"""Benchmark harness — load, analyze, and score benchmark results.

Provides a CLI-friendly interface for:
- Loading benchmark results from JSON files
- Running deployment readiness scoring on results
- Comparing multiple benchmark runs
- Generating summary reports
- Detecting performance regressions

Python 3.8+ compatible.  No external dependencies beyond stdlib.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Import the deployment scorer from the sibling ai_advisor package.
# Fall back to a lightweight stub so the harness can still run standalone.
# ---------------------------------------------------------------------------
try:
    from ai_advisor.scorer import DeploymentAssessment, assess_deployment_readiness
except ImportError:  # pragma: no cover -- fallback for isolated testing
    assess_deployment_readiness = None  # type: ignore[assignment]

    @dataclass(frozen=True)
    class DeploymentAssessment:  # type: ignore[no-redef]
        """Stub used only when ai_advisor is not installed."""

        ready: bool = False
        score: int = 0
        fps_headroom: float = 0.0
        latency_headroom: float = 0.0
        thermal_headroom: float = 0.0
        power_headroom: float = 0.0
        blocking_issues: List[str] = field(default_factory=list)
        warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkRun:
    """A single benchmark run with metadata and raw metrics."""

    name: str
    timestamp: str
    device_info: Dict[str, Any]
    metrics: Dict[str, Any]
    source_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Core harness
# ---------------------------------------------------------------------------


class BenchmarkHarness:
    """Load, score, compare, and summarise benchmark runs."""

    # -- Loading ------------------------------------------------------------

    @staticmethod
    def load_from_json(path: str) -> BenchmarkRun:
        """Load a single benchmark result from a JSON file.

        Expected JSON structure::

            {
                "name": "run-001",
                "timestamp": "2026-06-26T12:00:00",
                "device_info": {"platform": "Jetson Orin Nano", ...},
                "metrics": {
                    "fps_avg": 30.5,
                    "latency_p95_ms": 45.2,
                    "temp_max_c": 72.0,
                    "power_avg_watt": 12.5
                }
            }

        Raises
        ------
        FileNotFoundError
            If *path* does not exist.
        ValueError
            If required fields are missing or the file is not valid JSON.
        """
        if not os.path.isfile(path):
            raise FileNotFoundError("Benchmark file not found: {}".format(path))

        try:
            with open(path, "r", encoding="utf-8") as fh:
                data: Dict[str, Any] = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON in {}: {}".format(path, exc)) from exc

        if "metrics" not in data:
            raise ValueError("Missing required field 'metrics' in {}".format(path))

        return BenchmarkRun(
            name=data.get("name", os.path.splitext(os.path.basename(path))[0]),
            timestamp=data.get("timestamp", ""),
            device_info=data.get("device_info", {}),
            metrics=data["metrics"],
            source_path=path,
        )

    @staticmethod
    def load_from_directory(dir_path: str) -> List[BenchmarkRun]:
        """Load every ``*.json`` file in *dir_path* as a :class:`BenchmarkRun`.

        Files that fail to load are silently skipped so that one corrupt file
        does not abort the entire batch.
        """
        if not os.path.isdir(dir_path):
            raise FileNotFoundError("Directory not found: {}".format(dir_path))

        runs: List[BenchmarkRun] = []
        for fname in sorted(os.listdir(dir_path)):
            if fname.endswith(".json"):
                full = os.path.join(dir_path, fname)
                try:
                    runs.append(BenchmarkHarness.load_from_json(full))
                except (ValueError, FileNotFoundError):
                    continue
        return runs

    # -- Scoring ------------------------------------------------------------

    @staticmethod
    def score_run(
        run: BenchmarkRun,
        target_fps: float = 30.0,
        target_latency: float = 50.0,
        power_budget: float = 15.0,
        thermal_limit: float = 80.0,
    ) -> DeploymentAssessment:
        """Score a single benchmark run against deployment targets.

        Delegates to :func:`ai_advisor.scorer.assess_deployment_readiness`
        when available; otherwise returns a stub assessment.
        """
        if assess_deployment_readiness is not None:
            return assess_deployment_readiness(
                summary=run.metrics,
                target_fps=target_fps,
                target_latency_ms=target_latency,
                power_budget_watt=power_budget,
                thermal_limit_c=thermal_limit,
            )

        # Fallback stub (should rarely be reached in practice).
        return DeploymentAssessment(
            ready=False,
            score=0,
            fps_headroom=0.0,
            latency_headroom=0.0,
            thermal_headroom=0.0,
            power_headroom=0.0,
            blocking_issues=["Scorer unavailable — ai_advisor not installed"],
            warnings=[],
        )

    # -- Comparison ---------------------------------------------------------

    @staticmethod
    def compare_runs(
        baseline: BenchmarkRun,
        current: BenchmarkRun,
        regression_threshold: float = 0.1,
    ) -> Dict[str, Any]:
        """Compare *current* run against *baseline* and flag regressions.

        Returns a dict with per-metric deltas and a list of regressions.
        """
        metrics_to_compare = ("fps_avg", "latency_p95_ms", "temp_max_c", "power_avg_watt")

        deltas: Dict[str, Dict[str, Any]] = {}
        regressions: List[str] = []

        for key in metrics_to_compare:
            base_val = _safe_number(baseline.metrics, key)
            curr_val = _safe_number(current.metrics, key)
            if base_val is None or curr_val is None:
                continue

            delta = curr_val - base_val
            pct = delta / base_val if base_val != 0 else 0.0

            deltas[key] = {
                "baseline": base_val,
                "current": curr_val,
                "delta": round(delta, 4),
                "pct_change": round(pct, 4),
            }

            # FPS: lower is worse
            if key == "fps_avg" and pct < -regression_threshold:
                regressions.append(
                    "FPS regression: {:.1f} -> {:.1f} ({:.1%})".format(base_val, curr_val, pct)
                )
            # Latency, temp, power: higher is worse
            elif (
                key in ("latency_p95_ms", "temp_max_c", "power_avg_watt")
                and pct > regression_threshold
            ):
                regressions.append(
                    "{} regression: {:.1f} -> {:.1f} (+{:.1%})".format(key, base_val, curr_val, pct)
                )

        return {
            "baseline_name": baseline.name,
            "current_name": current.name,
            "deltas": deltas,
            "regressions": regressions,
            "regression_detected": len(regressions) > 0,
        }

    # -- Summary & reporting ------------------------------------------------

    @staticmethod
    def generate_summary(runs: List[BenchmarkRun]) -> Dict[str, Any]:
        """Generate a summary dict from one or more benchmark runs."""
        if not runs:
            return {"run_count": 0, "message": "No benchmark runs provided"}

        metric_keys = ("fps_avg", "latency_p95_ms", "temp_max_c", "power_avg_watt")
        aggregates: Dict[str, Dict[str, float]] = {}

        for key in metric_keys:
            raw = [_safe_number(r.metrics, key) for r in runs]
            values = [v for v in raw if v is not None]
            if not values:
                continue
            float_values = [float(v) for v in values]
            aggregates[key] = {
                "min": round(min(float_values), 4),
                "max": round(max(float_values), 4),
                "avg": round(sum(float_values) / len(float_values), 4),
                "count": len(float_values),
            }

        return {
            "run_count": len(runs),
            "runs": [{"name": r.name, "timestamp": r.timestamp} for r in runs],
            "aggregates": aggregates,
        }


# ---------------------------------------------------------------------------
# Standalone helpers
# ---------------------------------------------------------------------------


def detect_regression(
    baseline_fps: float,
    current_fps: float,
    threshold: float = 0.1,
) -> bool:
    """Return ``True`` if *current_fps* regressed beyond *threshold*.

    A regression is detected when the FPS drop exceeds *threshold* (10 % by
    default) of *baseline_fps*.
    """
    if baseline_fps <= 0:
        return False
    drop = (baseline_fps - current_fps) / baseline_fps
    return drop > threshold


def format_report(summary: Dict[str, Any]) -> str:
    """Render *summary* dict (from :meth:`BenchmarkHarness.generate_summary`)
    as a human-readable text table."""
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("  BENCHMARK SUMMARY REPORT")
    lines.append("=" * 60)
    lines.append("Runs analysed: {}".format(summary.get("run_count", 0)))

    # Run listing
    runs = summary.get("runs", [])
    if runs:
        lines.append("")
        lines.append("  {:<24s}  {:<28s}".format("Run name", "Timestamp"))
        lines.append("  " + "-" * 24 + "  " + "-" * 28)
        for entry in runs:
            lines.append(
                "  {:<24s}  {:<28s}".format(
                    str(entry.get("name", "")),
                    str(entry.get("timestamp", "")),
                )
            )

    # Aggregate table
    aggregates = summary.get("aggregates", {})
    if aggregates:
        lines.append("")
        lines.append(
            "  {:<20s} {:>8s} {:>8s} {:>8s} {:>5s}".format("Metric", "Min", "Max", "Avg", "N")
        )
        lines.append(
            "  " + "-" * 20 + " " + "-" * 8 + " " + "-" * 8 + " " + "-" * 8 + " " + "-" * 5
        )
        for metric, stats in aggregates.items():
            lines.append(
                "  {:<20s} {:>8.2f} {:>8.2f} {:>8.2f} {:>5d}".format(
                    metric,
                    stats.get("min", 0.0),
                    stats.get("max", 0.0),
                    stats.get("avg", 0.0),
                    stats.get("count", 0),
                )
            )

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_number(mapping: Dict[str, Any], key: str) -> Optional[float]:
    """Extract a numeric value, returning ``None`` if absent or non-numeric."""
    val = mapping.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
