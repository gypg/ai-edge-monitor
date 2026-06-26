from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any, Callable, Dict, Mapping, Optional

SummaryProvider = Callable[[], Mapping[str, Any]]


class PrometheusExporter:
    def __init__(self, summary_provider: Optional[SummaryProvider] = None) -> None:
        self._summary_provider = summary_provider or (lambda: {})

    def render_latest(self) -> str:
        return self.render(self._summary_provider())

    def render(self, summary: Mapping[str, Any]) -> str:
        metrics = [
            (
                "ai_edge_cpu_percent",
                "Average CPU utilization percent.",
                _float_value(summary.get("cpu_avg")),
            ),
            (
                "ai_edge_memory_used_bytes",
                "Average memory used in bytes.",
                _float_value(summary.get("mem_used_avg_mb")) * 1024.0 * 1024.0,
            ),
            (
                "ai_edge_power_watts",
                "Average power draw in watts.",
                _float_value(summary.get("power_avg_watt")),
            ),
            (
                "ai_edge_temperature_celsius",
                "Maximum observed temperature in Celsius.",
                _float_value(summary.get("temp_max_c")),
            ),
            (
                "ai_edge_inference_fps",
                "Inference frames per second.",
                _float_value(summary.get("inference_fps")),
            ),
            (
                "ai_edge_inference_latency_p95",
                "Inference P95 latency in ms.",
                _float_value(summary.get("inference_latency_p95_ms")),
            ),
            (
                "ai_edge_active_alerts",
                "Number of active alerts.",
                _float_value(summary.get("active_alerts")),
            ),
            (
                "ai_edge_deployment_score",
                "Deployment readiness score 0-100.",
                _float_value(summary.get("deployment_score")),
            ),
        ]
        lines = []
        for name, help_text, value in metrics:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"

    def start_http_server(self, port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
        exporter = self

        class MetricsHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path != "/metrics":
                    self.send_response(404)
                    self.end_headers()
                    return
                body = exporter.render_latest().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                return

        server = ThreadingHTTPServer((host, port), MetricsHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server


def _float_value(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
