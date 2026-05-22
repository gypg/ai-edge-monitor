from __future__ import annotations

import urllib.request
import unittest

from prometheus_exporter import PrometheusExporter


class PrometheusExporterTests(unittest.TestCase):
    def test_render_includes_help_type_and_metric_values(self) -> None:
        summary = {
            "cpu_avg": 12.5,
            "mem_used_avg_mb": 256.0,
            "power_avg_watt": 7.75,
            "temp_max_c": 63.0,
        }

        text = PrometheusExporter().render(summary)

        self.assertIn("# HELP ai_edge_cpu_percent Average CPU utilization percent.", text)
        self.assertIn("# TYPE ai_edge_cpu_percent gauge", text)
        self.assertIn("ai_edge_cpu_percent 12.5", text)
        self.assertIn("ai_edge_memory_used_bytes 268435456.0", text)
        self.assertIn("ai_edge_power_watts 7.75", text)
        self.assertIn("ai_edge_temperature_celsius 63.0", text)

    def test_render_uses_zero_for_empty_summary(self) -> None:
        text = PrometheusExporter().render({})

        self.assertIn("ai_edge_cpu_percent 0.0", text)
        self.assertIn("ai_edge_memory_used_bytes 0.0", text)
        self.assertIn("ai_edge_power_watts 0.0", text)
        self.assertIn("ai_edge_temperature_celsius 0.0", text)

    def test_render_latest_uses_provider(self) -> None:
        exporter = PrometheusExporter(lambda: {"cpu_avg": 5.0})

        self.assertIn("ai_edge_cpu_percent 5.0", exporter.render_latest())

    def test_http_server_exposes_metrics_endpoint(self) -> None:
        exporter = PrometheusExporter(lambda: {"cpu_avg": 3.0})
        server = exporter.start_http_server(0)
        port = server.server_address[1]
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2) as response:
                body = response.read().decode("utf-8")
        finally:
            server.shutdown()
            server.server_close()

        self.assertIn("ai_edge_cpu_percent 3.0", body)


if __name__ == "__main__":
    unittest.main()
