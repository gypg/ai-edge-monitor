"""Grafana Dashboard JSON generator.

Generates a Grafana-compatible dashboard JSON for the AI Edge Monitor
metrics exported via Prometheus.
"""

from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Panel definitions
# ---------------------------------------------------------------------------
_PANEL_DEFS: List[Dict[str, Any]] = [
    {
        "title": "CPU Usage",
        "metric": "ai_edge_cpu_percent",
        "type": "gauge",
        "gridPos": {"h": 6, "w": 8, "x": 0, "y": 0},
        "unit": "percent",
        "min": 0,
        "max": 100,
        "thresholds": [
            {"value": None, "color": "green"},
            {"value": 70, "color": "yellow"},
            {"value": 90, "color": "red"},
        ],
    },
    {
        "title": "CPU Usage (Timeline)",
        "metric": "ai_edge_cpu_percent",
        "type": "timeseries",
        "gridPos": {"h": 6, "w": 16, "x": 8, "y": 0},
        "unit": "percent",
        "min": 0,
        "max": 100,
    },
    {
        "title": "Memory Usage",
        "metric": "ai_edge_memory_used_bytes",
        "type": "gauge",
        "gridPos": {"h": 6, "w": 8, "x": 0, "y": 6},
        "unit": "bytes",
        "min": 0,
        "max": None,
        "thresholds": [
            {"value": None, "color": "green"},
            {"value": 80, "color": "yellow"},
            {"value": 95, "color": "red"},
        ],
    },
    {
        "title": "Memory Usage (Timeline)",
        "metric": "ai_edge_memory_used_bytes",
        "type": "timeseries",
        "gridPos": {"h": 6, "w": 16, "x": 8, "y": 6},
        "unit": "bytes",
        "min": 0,
        "max": None,
    },
    {
        "title": "Power Draw",
        "metric": "ai_edge_power_watts",
        "type": "gauge",
        "gridPos": {"h": 6, "w": 8, "x": 0, "y": 12},
        "unit": "watt",
        "min": 0,
        "max": None,
        "thresholds": [
            {"value": None, "color": "green"},
            {"value": 15, "color": "yellow"},
            {"value": 25, "color": "red"},
        ],
    },
    {
        "title": "Power Draw (Timeline)",
        "metric": "ai_edge_power_watts",
        "type": "timeseries",
        "gridPos": {"h": 6, "w": 16, "x": 8, "y": 12},
        "unit": "watt",
        "min": 0,
        "max": None,
    },
    {
        "title": "Temperature",
        "metric": "ai_edge_temperature_celsius",
        "type": "gauge",
        "gridPos": {"h": 6, "w": 8, "x": 0, "y": 18},
        "unit": "celsius",
        "min": 0,
        "max": 100,
        "thresholds": [
            {"value": None, "color": "green"},
            {"value": 65, "color": "yellow"},
            {"value": 80, "color": "red"},
        ],
    },
    {
        "title": "Temperature (Timeline)",
        "metric": "ai_edge_temperature_celsius",
        "type": "timeseries",
        "gridPos": {"h": 6, "w": 16, "x": 8, "y": 18},
        "unit": "celsius",
        "min": 0,
        "max": 100,
    },
    {
        "title": "Inference FPS",
        "metric": "ai_edge_inference_fps",
        "type": "timeseries",
        "gridPos": {"h": 6, "w": 12, "x": 0, "y": 24},
        "unit": "fps",
        "min": 0,
        "max": None,
    },
    {
        "title": "Inference Latency P95",
        "metric": "ai_edge_inference_latency_p95",
        "type": "timeseries",
        "gridPos": {"h": 6, "w": 12, "x": 12, "y": 24},
        "unit": "ms",
        "min": 0,
        "max": None,
    },
    {
        "title": "Active Alerts",
        "metric": "ai_edge_active_alerts",
        "type": "stat",
        "gridPos": {"h": 6, "w": 12, "x": 0, "y": 30},
        "unit": "short",
        "min": 0,
        "max": None,
        "thresholds": [
            {"value": None, "color": "green"},
            {"value": 1, "color": "yellow"},
            {"value": 5, "color": "red"},
        ],
    },
]


def _make_panel(
    panel_def: Dict[str, Any],
    panel_id: int,
    datasource: str,
) -> Dict[str, Any]:
    """Build a single Grafana panel dict from a definition."""
    panel_type = panel_def["type"]
    base: Dict[str, Any] = {
        "id": panel_id,
        "title": panel_def["title"],
        "type": panel_type,
        "datasource": {"type": "prometheus", "uid": datasource},
        "gridPos": panel_def["gridPos"],
        "targets": [
            {
                "expr": panel_def["metric"],
                "legendFormat": panel_def["title"],
                "refId": "A",
                "datasource": {"type": "prometheus", "uid": datasource},
            }
        ],
    }

    field_config: Dict[str, Any] = {"defaults": {}, "overrides": []}
    defaults = field_config["defaults"]

    if panel_def["unit"]:
        defaults["unit"] = panel_def["unit"]
    if panel_def["min"] is not None:
        defaults["min"] = panel_def["min"]
    if panel_def["max"] is not None:
        defaults["max"] = panel_def["max"]
    if panel_def.get("thresholds"):
        defaults["thresholds"] = {
            "mode": "absolute",
            "steps": panel_def["thresholds"],
        }

    base["fieldConfig"] = field_config

    if panel_type == "gauge":
        base["options"] = {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "orientation": "auto",
            "showThresholdLabels": False,
            "showThresholdMarkers": True,
        }
    elif panel_type == "stat":
        base["options"] = {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "colorMode": "background",
            "graphMode": "none",
            "justifyMode": "auto",
        }
    elif panel_type == "timeseries":
        base["options"] = {
            "tooltip": {"mode": "single"},
            "legend": {"displayMode": "list", "placement": "bottom"},
        }

    return base


# ---------------------------------------------------------------------------
# Public generator
# ---------------------------------------------------------------------------
class GrafanaDashboardGenerator:
    """Generates a Grafana dashboard JSON for AI Edge Monitor metrics."""

    def generate(
        self,
        title: str = "AI Edge Monitor",
        datasource: str = "Prometheus",
    ) -> Dict[str, Any]:
        """Generate Grafana dashboard JSON.

        Parameters
        ----------
        title:
            Dashboard title displayed in Grafana.
        datasource:
            Grafana datasource UID for Prometheus.

        Returns
        -------
        dict
            A dict that can be serialised to JSON and imported into Grafana.
        """
        panels: List[Dict[str, Any]] = [
            _make_panel(defn, idx + 1, datasource)
            for idx, defn in enumerate(_PANEL_DEFS)
        ]

        return {
            "id": None,
            "uid": "ai-edge-monitor",
            "title": title,
            "tags": ["ai-edge", "monitoring", "prometheus"],
            "timezone": "browser",
            "schemaVersion": 39,
            "version": 1,
            "refresh": "10s",
            "panels": panels,
            "templating": {
                "list": [
                    {
                        "name": "datasource",
                        "type": "datasource",
                        "query": "prometheus",
                        "current": {
                            "text": datasource,
                            "value": datasource,
                        },
                        "hide": 0,
                    }
                ]
            },
            "time": {"from": "now-1h", "to": "now"},
            "timepicker": {},
            "timezone": "browser",
            "editable": True,
            "fiscalYearStartMonth": 0,
            "liveNow": False,
            "weekStart": "",
        }
