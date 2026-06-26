"""Tests for Grafana dashboard JSON generation."""

from __future__ import annotations

import json

import pytest

from src.web_dashboard.grafana import GrafanaDashboardGenerator


@pytest.fixture()
def dashboard() -> dict:
    """Return a freshly generated dashboard dict."""
    return GrafanaDashboardGenerator().generate()


class TestDashboardHasPanels:
    """Verify the dashboard contains at least 7 panels."""

    def test_panel_count(self, dashboard: dict) -> None:
        panels = dashboard.get("panels", [])
        assert len(panels) >= 7, f"Expected >=7 panels, got {len(panels)}"

    def test_each_panel_has_title(self, dashboard: dict) -> None:
        for panel in dashboard["panels"]:
            assert "title" in panel
            assert panel["title"], "Panel title must not be empty"


class TestDashboardSchema:
    """Verify required Grafana dashboard fields are present."""

    def test_required_top_level_keys(self, dashboard: dict) -> None:
        required_keys = {"panels", "title", "templating", "schemaVersion"}
        missing = required_keys - dashboard.keys()
        assert not missing, f"Missing keys: {missing}"

    def test_title_value(self, dashboard: dict) -> None:
        assert dashboard["title"] == "AI Edge Monitor"

    def test_templating_list_exists(self, dashboard: dict) -> None:
        templating = dashboard["templating"]
        assert isinstance(templating, dict)
        assert "list" in templating
        assert isinstance(templating["list"], list)

    def test_schema_version_is_int(self, dashboard: dict) -> None:
        assert isinstance(dashboard["schemaVersion"], int)


class TestDashboardDatasource:
    """Verify Prometheus datasource is configured."""

    def test_datasource_type(self, dashboard: dict) -> None:
        for panel in dashboard["panels"]:
            ds = panel.get("datasource", {})
            assert ds.get("type") == "prometheus", (
                f"Panel '{panel['title']}' datasource type is not prometheus"
            )

    def test_templating_datasource(self, dashboard: dict) -> None:
        tvars = dashboard["templating"]["list"]
        ds_vars = [v for v in tvars if v.get("type") == "datasource"]
        assert len(ds_vars) >= 1, "Expected at least one datasource variable"
        assert ds_vars[0]["query"] == "prometheus"

    def test_custom_datasource_uid(self) -> None:
        gen = GrafanaDashboardGenerator()
        dash = gen.generate(datasource="MyProm")
        for panel in dash["panels"]:
            assert panel["datasource"]["uid"] == "MyProm"


class TestApiEndpoint:
    """Verify the /api/grafana-dashboard handler returns valid JSON."""

    def test_handler_returns_dict(self) -> None:
        from src.web_dashboard.api import handle_grafana

        result = handle_grafana("/api/grafana-dashboard", {}, {})
        assert isinstance(result, dict)

    def test_handler_returns_serializable_json(self) -> None:
        from src.web_dashboard.api import handle_grafana

        result = handle_grafana("/api/grafana-dashboard", {}, {})
        text = json.dumps(result)
        parsed = json.loads(text)
        assert parsed["title"] == "AI Edge Monitor"

    def test_handler_registered_in_routes(self) -> None:
        from src.web_dashboard.api import API_ROUTES

        assert "/api/grafana-dashboard" in API_ROUTES
