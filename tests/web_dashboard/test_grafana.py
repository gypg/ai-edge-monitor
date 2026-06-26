"""Tests for Grafana dashboard JSON generation."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from web_dashboard.grafana import GrafanaDashboardGenerator


class TestDashboardHasPanels(unittest.TestCase):
    """Verify the dashboard contains at least 7 panels."""

    def setUp(self) -> None:
        self.dashboard = GrafanaDashboardGenerator().generate()

    def test_panel_count(self) -> None:
        panels = self.dashboard.get("panels", [])
        self.assertGreaterEqual(len(panels), 7, f"Expected >=7 panels, got {len(panels)}")

    def test_each_panel_has_title(self) -> None:
        for panel in self.dashboard["panels"]:
            self.assertIn("title", panel)
            self.assertTrue(panel["title"], "Panel title must not be empty")


class TestDashboardSchema(unittest.TestCase):
    """Verify required Grafana dashboard fields are present."""

    def setUp(self) -> None:
        self.dashboard = GrafanaDashboardGenerator().generate()

    def test_required_top_level_keys(self) -> None:
        required_keys = {"panels", "title", "templating", "schemaVersion"}
        missing = required_keys - self.dashboard.keys()
        self.assertFalse(missing, f"Missing keys: {missing}")

    def test_title_value(self) -> None:
        self.assertEqual(self.dashboard["title"], "AI Edge Monitor")

    def test_templating_list_exists(self) -> None:
        templating = self.dashboard["templating"]
        self.assertIsInstance(templating, dict)
        self.assertIn("list", templating)
        self.assertIsInstance(templating["list"], list)

    def test_schema_version_is_int(self) -> None:
        self.assertIsInstance(self.dashboard["schemaVersion"], int)


class TestDashboardDatasource(unittest.TestCase):
    """Verify Prometheus datasource is configured."""

    def setUp(self) -> None:
        self.dashboard = GrafanaDashboardGenerator().generate()

    def test_datasource_type(self) -> None:
        for panel in self.dashboard["panels"]:
            ds = panel.get("datasource", {})
            self.assertEqual(ds.get("type"), "prometheus",
                             f"Panel '{panel['title']}' datasource type is not prometheus")

    def test_templating_datasource(self) -> None:
        tvars = self.dashboard["templating"]["list"]
        ds_vars = [v for v in tvars if v.get("type") == "datasource"]
        self.assertGreaterEqual(len(ds_vars), 1, "Expected at least one datasource variable")
        self.assertEqual(ds_vars[0]["query"], "prometheus")

    def test_custom_datasource_uid(self) -> None:
        gen = GrafanaDashboardGenerator()
        dash = gen.generate(datasource="MyProm")
        for panel in dash["panels"]:
            self.assertEqual(panel["datasource"]["uid"], "MyProm")


class TestApiEndpoint(unittest.TestCase):
    """Verify the /api/grafana-dashboard handler returns valid JSON."""

    def test_handler_returns_dict(self) -> None:
        from web_dashboard.api import handle_grafana

        result = handle_grafana("/api/grafana-dashboard", {}, {})
        self.assertIsInstance(result, dict)

    def test_handler_returns_serializable_json(self) -> None:
        from web_dashboard.api import handle_grafana

        result = handle_grafana("/api/grafana-dashboard", {}, {})
        text = json.dumps(result)
        parsed = json.loads(text)
        self.assertEqual(parsed["title"], "AI Edge Monitor")

    def test_handler_registered_in_routes(self) -> None:
        from web_dashboard.api import API_ROUTES

        self.assertIn("/api/grafana-dashboard", API_ROUTES)


if __name__ == "__main__":
    unittest.main()
