"""ROS2 bridge node -- publishes monitoring data as ROS2 topics."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import rclpy
    from rclpy.node import Node as RclNode
    from std_msgs.msg import Float64, String

    HAS_ROS2 = True
except ImportError:
    HAS_ROS2 = False
    RclNode = object  # type: ignore[assignment,misc]
    Float64 = None  # type: ignore[assignment]
    String = None  # type: ignore[assignment]


_SYSTEM_TOPICS: Dict[str, str] = {
    "cpu_percent": "/system/cpu_percent",
    "memory_mb": "/system/memory_mb",
    "power_watt": "/system/power_watt",
    "temperature_c": "/system/temperature_c",
    "gpu_utilization": "/system/gpu_utilization",
}

_INFERENCE_TOPICS: Dict[str, str] = {
    "fps": "/inference/fps",
    "latency_p95": "/inference/latency_p95",
    "gpu_util": "/inference/gpu_util",
}

_SUMMARY_KEY_MAP: Dict[str, str] = {
    "cpu_percent": "cpu_avg",
    "memory_mb": "mem_used_avg_mb",
    "power_watt": "power_avg_watt",
    "temperature_c": "temp_max_c",
    "gpu_utilization": "gpu_percent",
}


class MonitorNode(RclNode if HAS_ROS2 else object):  # type: ignore[misc]
    """ROS2 node publishing system + inference monitoring data."""

    def __init__(self, node_name: str = "ai_edge_monitor") -> None:
        if HAS_ROS2:
            super().__init__(node_name)
            self._pubs: Dict[str, Any] = {}
            for key, topic in _SYSTEM_TOPICS.items():
                self._pubs[key] = self.create_publisher(Float64, topic, 10)
            for key, topic in _INFERENCE_TOPICS.items():
                self._pubs[key] = self.create_publisher(Float64, topic, 10)
            self._status_pub = self.create_publisher(String, "/monitor/status", 10)
            self.get_logger().info("MonitorNode started")

    def publish_metrics(self, summary: Dict[str, Any]) -> None:
        """Publish system metrics from AggregatorAnalyzer.get_summary_dict()."""
        if not HAS_ROS2:
            return
        for pub_key, summary_key in _SUMMARY_KEY_MAP.items():
            val = summary.get(summary_key)
            if val is not None:
                msg = Float64()
                msg.data = float(val)
                self._pubs[pub_key].publish(msg)

    def publish_inference(self, inference_results: Any) -> None:
        """Publish inference metrics."""
        if not HAS_ROS2:
            return
        mapping = {
            "fps": getattr(inference_results, "fps", None),
            "latency_p95": getattr(inference_results, "latency_p95_ms", None),
            "gpu_util": getattr(inference_results, "gpu_util_avg", None),
        }
        for key, val in mapping.items():
            if val is not None:
                msg = Float64()
                msg.data = float(val)
                self._pubs[key].publish(msg)

    def publish_status(self, status_dict: Dict[str, Any]) -> None:
        """Publish JSON status string."""
        if not HAS_ROS2:
            return
        msg = String()
        msg.data = json.dumps(status_dict, ensure_ascii=False, default=str)
        self._status_pub.publish(msg)


def create_monitor_node(node_name: str = "ai_edge_monitor") -> Optional[MonitorNode]:
    """Factory: create node or return None with warning if ROS2 unavailable."""
    if not HAS_ROS2:
        logger.warning("ROS2 (rclpy) not available, MonitorNode disabled")
        return None
    return MonitorNode(node_name)
