"""Web Dashboard -- lightweight real-time monitoring UI for edge devices.

Provides a single-page HTML dashboard with:
  - Real-time CPU / Memory / Power / Temperature charts
  - Alert panel with active alerts and history
  - System health overview (guardian status)
  - Network / Disk I/O gauges

Design constraints:
  - Zero frontend build step (single HTML file with inline CSS/JS)
  - Chart.js loaded from CDN (no npm/node required)
  - Backend uses only stdlib http.server + threading
  - Minimal memory footprint for Jetson / Raspberry Pi
"""

from .server import DashboardServer, create_dashboard_app

__all__ = ["DashboardServer", "create_dashboard_app"]
