"""Lightweight HTTP server for the dashboard.

Uses only stdlib (http.server + threading + json).  Serves the single-page
HTML dashboard at ``/`` and proxies API calls to the handler registry.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from .api import API_ROUTES, ApiHandler
from .html_template import DASHBOARD_HTML

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------
class _DashboardHandler(BaseHTTPRequestHandler):
    """Handles GET requests for the dashboard UI and API endpoints."""

    # Shared context dict set by DashboardServer before server starts.
    context: Dict[str, Any] = {}

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if path == "/":
            self._serve_html()
        elif path in API_ROUTES:
            self._serve_api(path, params, API_ROUTES[path])
        else:
            self._json_response({"error": "not found"}, status=404)

    def _serve_html(self) -> None:
        html_bytes = DASHBOARD_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html_bytes)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(html_bytes)

    def _serve_api(
        self, path: str, params: Dict[str, str], handler: ApiHandler
    ) -> None:
        try:
            data = handler(path, params, self.context)
            self._json_response(data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("API handler error for %s", path)
            self._json_response(
                {"error": str(exc)}, status=500
            )

    def _json_response(
        self, data: Any, status: int = 200
    ) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        # Suppress default stderr logging; use stdlib logger instead.
        logger.debug(fmt, *args)


# ---------------------------------------------------------------------------
# Public server wrapper
# ---------------------------------------------------------------------------
class DashboardServer:
    """Thin wrapper around ``ThreadingHTTPServer``.

    Parameters
    ----------
    host:
        Bind address (default ``"0.0.0.0"``).
    port:
        Bind port (default ``17429``).
    context:
        Dict of data providers wired to API handlers.
        Expected keys: ``summary_provider``, ``alert_manager``,
        ``guardian``, ``system_monitor``, ``config``.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 17429,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._host = host
        self._port = port
        self._context = context or {}
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the HTTP server in a background daemon thread."""
        _DashboardHandler.context = self._context
        self._server = ThreadingHTTPServer(
            (self._host, self._port), _DashboardHandler
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="dashboard-server",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Dashboard started at http://%s:%d", self._host, self._port
        )

    def stop(self) -> None:
        """Shut down the HTTP server gracefully."""
        if self._server is not None:
            self._server.shutdown()
            logger.info("Dashboard stopped")

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"


def create_dashboard_app(
    host: str = "0.0.0.0",
    port: int = 17429,
    context: Optional[Dict[str, Any]] = None,
) -> DashboardServer:
    """Factory function for creating a configured dashboard server."""
    return DashboardServer(host=host, port=port, context=context)
