"""REST API handlers for the dashboard.

Each handler is a pure function that accepts a data context dict and returns
a JSON-serializable dict.  The server layer maps URL paths to handlers.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Handler type
# ---------------------------------------------------------------------------
# A handler receives (path, query_params, context) and returns a dict.
ApiHandler = Callable[[str, Dict[str, str], Dict[str, Any]], Dict[str, Any]]


def _ts_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# GET /api/summary -- current monitoring window summary
# ---------------------------------------------------------------------------
def handle_summary(
    _path: str,
    _params: Dict[str, str],
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Return the latest WindowSummary dict from AggregatorAnalyzer."""
    summary_provider: Optional[Callable[[], Dict[str, Any]]] = ctx.get(
        "summary_provider"
    )
    if summary_provider is None:
        return {"error": "summary_provider not configured", "ts_ms": _ts_ms()}
    try:
        data = summary_provider()
        data["ts_ms"] = _ts_ms()
        return data
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "ts_ms": _ts_ms()}


# ---------------------------------------------------------------------------
# GET /api/alerts -- active alerts + history + stats
# ---------------------------------------------------------------------------
def handle_alerts(
    _path: str,
    params: Dict[str, str],
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Return alert data from AlertManager."""
    alert_manager = ctx.get("alert_manager")
    if alert_manager is None:
        return {
            "active_alerts": [],
            "alert_history": [],
            "stats": {},
            "ts_ms": _ts_ms(),
        }
    try:
        raw = alert_manager.export_alerts_json()
        # export_alerts_json returns a JSON string; parse to dict.
        data = json.loads(raw) if isinstance(raw, str) else raw
        data["ts_ms"] = _ts_ms()
        return data
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "ts_ms": _ts_ms()}


# ---------------------------------------------------------------------------
# GET /api/health -- runtime guardian health status
# ---------------------------------------------------------------------------
def handle_health(
    _path: str,
    _params: Dict[str, str],
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Return RuntimeGuardian health report."""
    guardian = ctx.get("guardian")
    if guardian is None:
        return {"status": "not_configured", "ts_ms": _ts_ms()}
    try:
        health = guardian.get_health()
        health["ts_ms"] = _ts_ms()
        return health
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "ts_ms": _ts_ms()}


# ---------------------------------------------------------------------------
# GET /api/system -- extended system metrics (network, disk, process)
# ---------------------------------------------------------------------------
def handle_system(
    _path: str,
    _params: Dict[str, str],
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Return extended system metrics from SystemMonitor."""
    system_monitor = ctx.get("system_monitor")
    if system_monitor is None:
        return {"status": "not_configured", "ts_ms": _ts_ms()}
    try:
        summary = system_monitor.collect_system_summary()
        # Add rate data
        try:
            net_rates = system_monitor.collect_network_io_rates()
            summary.update(net_rates)
        except Exception:  # noqa: BLE001
            pass
        try:
            disk_rates = system_monitor.collect_disk_io_rates()
            summary.update(disk_rates)
        except Exception:  # noqa: BLE001
            pass
        summary["ts_ms"] = _ts_ms()
        return summary
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "ts_ms": _ts_ms()}


# ---------------------------------------------------------------------------
# GET /api/config -- current monitoring configuration
# ---------------------------------------------------------------------------
def handle_config(
    _path: str,
    _params: Dict[str, str],
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Return current configuration summary."""
    config = ctx.get("config")
    if config is None:
        return {"status": "not_configured", "ts_ms": _ts_ms()}
    try:
        return {
            "duration_sec": getattr(config, "duration_sec", None),
            "sample_interval_ms": getattr(config, "sample_interval_ms", None),
            "exporters": getattr(config, "exporters", []),
            "thresholds": getattr(config, "thresholds", {}),
            "probe": getattr(config, "probe", None),
            "power_source": getattr(config, "power_source", None),
            "ts_ms": _ts_ms(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "ts_ms": _ts_ms()}


# ---------------------------------------------------------------------------
# GET /api/inference -- inference performance data
# ---------------------------------------------------------------------------
def handle_inference(
    _path: str,
    _params: Dict[str, str],
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Return inference performance data from InferenceMonitor."""
    inference_monitor = ctx.get("inference_monitor")
    if inference_monitor is None:
        return {"status": "not_configured", "ts_ms": _ts_ms()}
    try:
        results = inference_monitor.results
        return {
            "fps": results.fps,
            "latency_p50_ms": results.latency_p50_ms,
            "latency_p95_ms": results.latency_p95_ms,
            "latency_p99_ms": results.latency_p99_ms,
            "frame_count": results.total_inferences,
            "gpu_util_during_inference": results.gpu_util_avg,
            "power_during_inference": results.power_avg_watt,
            "ts_ms": _ts_ms(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "ts_ms": _ts_ms()}


from .grafana import GrafanaDashboardGenerator

# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------
_API_ROUTES_CORE: Dict[str, ApiHandler] = {
    "/api/summary": handle_summary,
    "/api/alerts": handle_alerts,
    "/api/health": handle_health,
    "/api/system": handle_system,
    "/api/config": handle_config,
}


# ---------------------------------------------------------------------------
# GET /api/grafana-dashboard -- Grafana dashboard JSON export
# ---------------------------------------------------------------------------
def handle_grafana(
    _path: str,
    _params: Dict[str, str],
    _ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a Grafana dashboard JSON for AI Edge Monitor metrics."""
    gen = GrafanaDashboardGenerator()
    return gen.generate()


# ---------------------------------------------------------------------------
# GET /api/diagnosis -- AI Advisor diagnostic results
# ---------------------------------------------------------------------------
def handle_diagnosis(
    _path: str,
    _params: Dict[str, str],
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Return AI Advisor diagnosis and deployment score."""
    ai_advisor = ctx.get("ai_advisor")
    if ai_advisor is None:
        return {"diagnoses": [], "deployment_score": None, "ts_ms": _ts_ms()}
    try:
        summary_provider = ctx.get("summary_provider")
        summary = summary_provider() if summary_provider else {}
        diagnoses = ai_advisor.diagnose(summary)
        scorer = ctx.get("deployment_scorer")
        score = scorer(summary) if scorer else None
        return {
            "diagnoses": [
                {
                    "rule_name": d.rule_name,
                    "category": d.category,
                    "priority": d.priority,
                    "suggestion": d.suggestion,
                    "evidence": d.evidence,
                }
                for d in diagnoses
            ],
            "deployment_score": {
                "total": score.score,
                "ready": score.ready,
                "verdict": score.verdict if hasattr(score, "verdict") else ("ready" if score.ready else "not_ready"),
                "bottlenecks": getattr(score, "bottlenecks", score.blocking_issues),
            }
            if score
            else None,
            "ts_ms": _ts_ms(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "ts_ms": _ts_ms()}


# ---------------------------------------------------------------------------
# GET /api/history -- historical data replay
# ---------------------------------------------------------------------------
def handle_history(
    _path: str,
    params: Dict[str, str],
    ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Return historical metric records for replay."""
    history = ctx.get("history_provider")
    if history is None:
        return {"records": [], "total": 0, "ts_ms": _ts_ms()}
    try:
        from_ms = int(params.get("from", "0"))
        to_ms = int(params.get("to", str(_ts_ms())))
        limit = min(int(params.get("limit", "1000")), 10000)
        records = history.query(from_ms, to_ms, limit)
        return {"records": records, "total": len(records), "ts_ms": _ts_ms()}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "ts_ms": _ts_ms()}


API_ROUTES: Dict[str, ApiHandler] = {
    **_API_ROUTES_CORE,
    "/api/grafana-dashboard": handle_grafana,
    "/api/inference": handle_inference,
    "/api/diagnosis": handle_diagnosis,
    "/api/history": handle_history,
}
