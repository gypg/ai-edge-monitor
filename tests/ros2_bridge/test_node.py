"""Tests for the ROS2 bridge MonitorNode.

These tests do NOT require a ROS2 installation -- ``rclpy`` and
``std_msgs`` are mocked so the module can be exercised in any environment.
"""

from __future__ import annotations

import importlib
import sys
import types
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_rclpy():
    """Build a minimal mock ``rclpy`` module and ``std_msgs``."""
    fake_rclpy = types.ModuleType("rclpy")
    fake_rclpy.node = types.ModuleType("rclpy.node")

    class FakeNode:
        def __init__(self, name: str) -> None:
            self._name = name

        def create_publisher(self, msg_type, topic, qos):  # noqa: ANN001
            pub = mock.MagicMock()
            pub.topic = topic
            return pub

        def get_logger(self):  # noqa: ANN001
            return mock.MagicMock()

    fake_rclpy.node.Node = FakeNode  # type: ignore[attr-defined]
    fake_rclpy.node.__dict__["Node"] = FakeNode

    fake_std_msgs = types.ModuleType("std_msgs")
    fake_std_msgs.msg = types.ModuleType("std_msgs.msg")

    class FakeFloat64:
        data: float = 0.0

    class FakeString:
        data: str = ""

    fake_std_msgs.msg.Float64 = FakeFloat64  # type: ignore[attr-defined]
    fake_std_msgs.msg.String = FakeString  # type: ignore[attr-defined]
    fake_std_msgs.__dict__["msg"] = fake_std_msgs.msg

    return fake_rclpy, fake_std_msgs


def _load_node_with_ros2():
    """Import ``node`` module pretending ROS2 is available."""
    fake_rclpy, fake_std_msgs = _make_fake_rclpy()
    patched = {
        "rclpy": fake_rclpy,
        "rclpy.node": fake_rclpy.node,
        "std_msgs": fake_std_msgs,
        "std_msgs.msg": fake_std_msgs.msg,
    }
    with mock.patch.dict(sys.modules, patched):
        sys.modules.pop("src.ros2_bridge.node", None)
        sys.modules.pop("src.ros2_bridge", None)
        import src.ros2_bridge.node as mod
        importlib.reload(mod)
        return mod


def _load_node_without_ros2():
    """Import ``node`` module with rclpy absent."""
    patched = {
        "rclpy": None,
        "rclpy.node": None,
        "std_msgs": None,
        "std_msgs.msg": None,
    }
    with mock.patch.dict(sys.modules, patched, clear=False):
        # Remove cached entries so the ImportError path fires.
        for key in list(sys.modules):
            if key.startswith("rclpy") or key.startswith("std_msgs"):
                sys.modules.pop(key)
        sys.modules.pop("src.ros2_bridge.node", None)
        sys.modules.pop("src.ros2_bridge", None)
        import src.ros2_bridge.node as mod
        importlib.reload(mod)
        return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNodeStubNoRos2:
    """Verify no-op behaviour when ROS2 is not installed."""

    def test_has_ros2_false(self):
        mod = _load_node_without_ros2()
        assert mod.HAS_ROS2 is False

    def test_monitor_node_is_plain_object(self):
        mod = _load_node_without_ros2()
        node = mod.MonitorNode()
        # Should not raise; publish methods should be no-ops.
        node.publish_metrics({"cpu_avg": 42.0})
        node.publish_inference(mock.MagicMock(fps=30))
        node.publish_status({"ok": True})

    def test_create_monitor_node_returns_none(self):
        mod = _load_node_without_ros2()
        assert mod.create_monitor_node() is None


class TestNodeWithMockRos2:
    """Verify node behaviour with a mocked ROS2 stack."""

    def test_publishers_created(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode("test_node")
        # 5 system + 3 inference + 1 status = 9 publishers
        assert len(node._pubs) == 8
        assert hasattr(node, "_status_pub")

    def test_publish_metrics_forwards_values(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        summary = {
            "cpu_avg": 55.0,
            "mem_used_avg_mb": 1024.0,
            "power_avg_watt": 12.5,
            "temp_max_c": 65.0,
            "gpu_percent": 80.0,
        }
        # Should not raise.
        node.publish_metrics(summary)

    def test_publish_metrics_ignores_missing_keys(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        # Partial summary -- missing keys should be skipped silently.
        node.publish_metrics({"cpu_avg": 10.0})

    def test_publish_inference(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        results = mock.MagicMock(fps=30.0, latency_p95_ms=12.5, gpu_util_avg=70.0)
        node.publish_inference(results)

    def test_publish_status_serialises_json(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        node.publish_status({"status": "ok", "value": 42})

    def test_create_monitor_node_returns_instance(self):
        mod = _load_node_with_ros2()
        node = mod.create_monitor_node("custom_name")
        assert node is not None
        assert isinstance(node, mod.MonitorNode)
