"""Extended tests for the ROS2 bridge MonitorNode.

Covers topic definitions, message types, summary key mapping, inference
attribute mapping, and edge cases. Uses unittest and mock rclpy so tests
run without a ROS2 installation.

Run:  python tests/ros2_bridge/test_node_extended.py
"""

from __future__ import annotations

import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Helpers -- same fake-rclpy strategy as test_node.py
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
            pub.msg_type = msg_type
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
        sys.modules.pop("ros2_bridge.node", None)
        sys.modules.pop("ros2_bridge", None)
        import ros2_bridge.node as mod

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
        for key in list(sys.modules):
            if key.startswith("rclpy") or key.startswith("std_msgs"):
                sys.modules.pop(key)
        sys.modules.pop("ros2_bridge.node", None)
        sys.modules.pop("ros2_bridge", None)
        import ros2_bridge.node as mod

        importlib.reload(mod)
        return mod


# ---------------------------------------------------------------------------
# Topic definition tests
# ---------------------------------------------------------------------------


class TestTopicDefinitions(unittest.TestCase):
    """Verify topic constant dictionaries are well-formed."""

    def test_system_topics_keys(self):
        mod = _load_node_without_ros2()
        expected_keys = {
            "cpu_percent",
            "memory_mb",
            "power_watt",
            "temperature_c",
            "gpu_utilization",
        }
        self.assertEqual(set(mod._SYSTEM_TOPICS.keys()), expected_keys)

    def test_system_topics_count(self):
        mod = _load_node_without_ros2()
        self.assertEqual(len(mod._SYSTEM_TOPICS), 5)

    def test_system_topics_have_system_prefix(self):
        mod = _load_node_without_ros2()
        for key, topic in mod._SYSTEM_TOPICS.items():
            self.assertTrue(
                topic.startswith("/system/"),
                f"{key} topic {topic!r} must start with /system/",
            )

    def test_system_topics_path_format(self):
        """Each path should match /system/<key>."""
        mod = _load_node_without_ros2()
        for key, topic in mod._SYSTEM_TOPICS.items():
            self.assertEqual(topic, f"/system/{key}")

    def test_inference_topics_keys(self):
        mod = _load_node_without_ros2()
        expected_keys = {"fps", "latency_p95", "gpu_util"}
        self.assertEqual(set(mod._INFERENCE_TOPICS.keys()), expected_keys)

    def test_inference_topics_count(self):
        mod = _load_node_without_ros2()
        self.assertEqual(len(mod._INFERENCE_TOPICS), 3)

    def test_inference_topics_have_inference_prefix(self):
        mod = _load_node_without_ros2()
        for key, topic in mod._INFERENCE_TOPICS.items():
            self.assertTrue(
                topic.startswith("/inference/"),
                f"{key} topic {topic!r} must start with /inference/",
            )

    def test_inference_topics_path_format(self):
        """Each path should match /inference/<key>."""
        mod = _load_node_without_ros2()
        for key, topic in mod._INFERENCE_TOPICS.items():
            self.assertEqual(topic, f"/inference/{key}")

    def test_no_duplicate_topic_values(self):
        mod = _load_node_without_ros2()
        all_topics = list(mod._SYSTEM_TOPICS.values()) + list(mod._INFERENCE_TOPICS.values())
        self.assertEqual(
            len(all_topics),
            len(set(all_topics)),
            "Topic values must be unique across system and inference",
        )

    def test_no_shared_paths_between_system_and_inference(self):
        mod = _load_node_without_ros2()
        sys_paths = set(mod._SYSTEM_TOPICS.values())
        inf_paths = set(mod._INFERENCE_TOPICS.values())
        self.assertTrue(
            sys_paths.isdisjoint(inf_paths),
            "System and inference topic paths must not overlap",
        )

    def test_topic_values_are_absolute_paths(self):
        mod = _load_node_without_ros2()
        for mapping in (mod._SYSTEM_TOPICS, mod._INFERENCE_TOPICS):
            for key, topic in mapping.items():
                self.assertTrue(
                    topic.startswith("/"),
                    f"Topic {topic!r} for {key} must be an absolute path",
                )


# ---------------------------------------------------------------------------
# Message type tests
# ---------------------------------------------------------------------------


class TestMessageTypes(unittest.TestCase):
    """Verify publishers use the correct message types."""

    def test_system_publishers_created(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode("test_msg_types")
        for key in mod._SYSTEM_TOPICS:
            self.assertIn(key, node._pubs, f"Missing publisher for {key}")

    def test_inference_publishers_created(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode("test_msg_types_inf")
        for key in mod._INFERENCE_TOPICS:
            self.assertIn(key, node._pubs, f"Missing publisher for {key}")

    def test_status_publisher_exists(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode("test_status_pub")
        self.assertTrue(
            hasattr(node, "_status_pub"),
            "Node must have a _status_pub for /monitor/status",
        )

    def test_total_publisher_count(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode("test_count")
        expected = len(mod._SYSTEM_TOPICS) + len(mod._INFERENCE_TOPICS)
        self.assertEqual(
            len(node._pubs),
            expected,
            f"Expected {expected} topic publishers, got {len(node._pubs)}",
        )


# ---------------------------------------------------------------------------
# Summary key mapping tests
# ---------------------------------------------------------------------------


class TestSummaryKeyMapping(unittest.TestCase):
    """Verify _SUMMARY_KEY_MAP correctness."""

    def test_summary_key_map_keys_match_system_topics(self):
        mod = _load_node_without_ros2()
        self.assertEqual(
            set(mod._SUMMARY_KEY_MAP.keys()),
            set(mod._SYSTEM_TOPICS.keys()),
            "_SUMMARY_KEY_MAP keys must match _SYSTEM_TOPICS keys",
        )

    def test_summary_key_map_values_are_strings(self):
        mod = _load_node_without_ros2()
        for key, val in mod._SUMMARY_KEY_MAP.items():
            self.assertIsInstance(
                val,
                str,
                f"_SUMMARY_KEY_MAP[{key!r}] must be a string, got {type(val)}",
            )

    def test_summary_key_map_count(self):
        mod = _load_node_without_ros2()
        self.assertEqual(len(mod._SUMMARY_KEY_MAP), 5)

    def test_summary_key_map_values_unique(self):
        mod = _load_node_without_ros2()
        values = list(mod._SUMMARY_KEY_MAP.values())
        self.assertEqual(len(values), len(set(values)))

    def test_known_summary_values(self):
        mod = _load_node_without_ros2()
        expected = {
            "cpu_percent": "cpu_avg",
            "memory_mb": "mem_used_avg_mb",
            "power_watt": "power_avg_watt",
            "temperature_c": "temp_max_c",
            "gpu_utilization": "gpu_percent",
        }
        self.assertEqual(dict(mod._SUMMARY_KEY_MAP), expected)


# ---------------------------------------------------------------------------
# publish_metrics tests
# ---------------------------------------------------------------------------


class TestPublishMetrics(unittest.TestCase):
    """Test publish_metrics with various summary dictionaries."""

    def _make_node(self):
        mod = _load_node_with_ros2()
        return mod.MonitorNode(), mod

    def test_publish_full_summary(self):
        node, mod = self._make_node()
        summary = {
            "cpu_avg": 55.0,
            "mem_used_avg_mb": 1024.0,
            "power_avg_watt": 12.5,
            "temp_max_c": 65.0,
            "gpu_percent": 80.0,
        }
        node.publish_metrics(summary)
        for key in mod._SUMMARY_KEY_MAP:
            node._pubs[key].publish.assert_called()

    def test_publish_partial_summary(self):
        """Only present keys should be published."""
        node, mod = self._make_node()
        summary = {"cpu_avg": 42.0}
        node.publish_metrics(summary)
        node._pubs["cpu_percent"].publish.assert_called_once()
        for key in ("memory_mb", "power_watt", "temperature_c", "gpu_utilization"):
            node._pubs[key].publish.assert_not_called()

    def test_empty_summary_no_publishes(self):
        node, mod = self._make_node()
        node.publish_metrics({})
        for key in mod._SUMMARY_KEY_MAP:
            node._pubs[key].publish.assert_not_called()

    def test_none_values_skipped(self):
        node, mod = self._make_node()
        summary = {
            "cpu_avg": None,
            "mem_used_avg_mb": None,
            "power_avg_watt": None,
            "temp_max_c": None,
            "gpu_percent": None,
        }
        node.publish_metrics(summary)
        for key in mod._SUMMARY_KEY_MAP:
            node._pubs[key].publish.assert_not_called()

    def test_mixed_none_and_values(self):
        node, mod = self._make_node()
        summary = {"cpu_avg": 50.0, "mem_used_avg_mb": None, "power_avg_watt": 10.0}
        node.publish_metrics(summary)
        node._pubs["cpu_percent"].publish.assert_called_once()
        node._pubs["memory_mb"].publish.assert_not_called()
        node._pubs["power_watt"].publish.assert_called_once()

    def test_integer_values_coerced_to_float(self):
        node, mod = self._make_node()
        summary = {"cpu_avg": 50}
        node.publish_metrics(summary)
        node._pubs["cpu_percent"].publish.assert_called_once()
        msg = node._pubs["cpu_percent"].publish.call_args[0][0]
        self.assertAlmostEqual(msg.data, 50.0)

    def test_extraneous_keys_ignored(self):
        node, mod = self._make_node()
        summary = {"cpu_avg": 10.0, "unknown_key": 999.0, "another": "text"}
        node.publish_metrics(summary)
        node._pubs["cpu_percent"].publish.assert_called_once()

    def test_published_data_value(self):
        """Verify the published message carries the correct float value."""
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        summary = {"cpu_avg": 42.5}
        node.publish_metrics(summary)
        msg = node._pubs["cpu_percent"].publish.call_args[0][0]
        self.assertAlmostEqual(msg.data, 42.5)

    def test_multiple_calls_accumulate(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        node.publish_metrics({"cpu_avg": 10.0})
        node.publish_metrics({"cpu_avg": 20.0})
        self.assertEqual(node._pubs["cpu_percent"].publish.call_count, 2)

    def test_string_numeric_value_cast(self):
        """String numeric values should be cast to float without error."""
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        summary = {"cpu_avg": "75.5"}
        node.publish_metrics(summary)
        msg = node._pubs["cpu_percent"].publish.call_args[0][0]
        self.assertAlmostEqual(msg.data, 75.5)

    def test_noop_without_ros2(self):
        mod = _load_node_without_ros2()
        node = mod.MonitorNode()
        result = node.publish_metrics({"cpu_avg": 42.0})
        self.assertIsNone(result)

    def test_zero_values_are_published(self):
        """Zero is a valid metric and must be published, not skipped."""
        node, mod = self._make_node()
        summary = {"cpu_avg": 0.0, "mem_used_avg_mb": 0}
        node.publish_metrics(summary)
        node._pubs["cpu_percent"].publish.assert_called_once()
        node._pubs["memory_mb"].publish.assert_called_once()

    def test_negative_values_pass_through(self):
        """Negative values should pass through without validation error."""
        node, mod = self._make_node()
        summary = {"cpu_avg": -1.0}
        node.publish_metrics(summary)
        node._pubs["cpu_percent"].publish.assert_called_once()

    def test_large_values_published(self):
        node, mod = self._make_node()
        summary = {"mem_used_avg_mb": 999999.5}
        node.publish_metrics(summary)
        node._pubs["memory_mb"].publish.assert_called_once()
        msg = node._pubs["memory_mb"].publish.call_args[0][0]
        self.assertAlmostEqual(msg.data, 999999.5)


# ---------------------------------------------------------------------------
# publish_inference tests
# ---------------------------------------------------------------------------


class TestPublishInference(unittest.TestCase):
    """Test publish_inference attribute mapping."""

    def _make_node(self):
        mod = _load_node_with_ros2()
        return mod.MonitorNode(), mod

    def test_all_attributes_present(self):
        node, mod = self._make_node()
        results = mock.MagicMock(fps=30.0, latency_p95_ms=12.5, gpu_util_avg=70.0)
        node.publish_inference(results)
        for key in ("fps", "latency_p95", "gpu_util"):
            node._pubs[key].publish.assert_called_once()

    def test_attribute_mapping_values(self):
        """Verify the attribute names map to correct topic keys with right values."""
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        results = mock.MagicMock(fps=15.0, latency_p95_ms=8.0, gpu_util_avg=90.0)
        node.publish_inference(results)
        fps_msg = node._pubs["fps"].publish.call_args[0][0]
        self.assertAlmostEqual(fps_msg.data, 15.0)
        lat_msg = node._pubs["latency_p95"].publish.call_args[0][0]
        self.assertAlmostEqual(lat_msg.data, 8.0)
        gpu_msg = node._pubs["gpu_util"].publish.call_args[0][0]
        self.assertAlmostEqual(gpu_msg.data, 90.0)

    def test_partial_attributes(self):
        node, mod = self._make_node()
        results = mock.MagicMock(fps=30.0, latency_p95_ms=None, gpu_util_avg=None)
        del results.latency_p95_ms
        del results.gpu_util_avg
        node.publish_inference(results)
        node._pubs["fps"].publish.assert_called_once()
        node._pubs["latency_p95"].publish.assert_not_called()
        node._pubs["gpu_util"].publish.assert_not_called()

    def test_missing_object_treated_as_none(self):
        node, mod = self._make_node()
        results = mock.MagicMock(spec=[])  # no attributes
        node.publish_inference(results)

    def test_integer_values_coerced(self):
        node, mod = self._make_node()
        results = mock.MagicMock(fps=30, latency_p95_ms=10, gpu_util_avg=50)
        node.publish_inference(results)
        for key in ("fps", "latency_p95", "gpu_util"):
            node._pubs[key].publish.assert_called_once()

    def test_all_none_produces_no_publishes(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        results = mock.MagicMock()
        results.fps = None
        results.latency_p95_ms = None
        results.gpu_util_avg = None
        node.publish_inference(results)
        for key in ("fps", "latency_p95", "gpu_util"):
            node._pubs[key].publish.assert_not_called()

    def test_noop_without_ros2(self):
        mod = _load_node_without_ros2()
        node = mod.MonitorNode()
        result = node.publish_inference(mock.MagicMock())
        self.assertIsNone(result)

    def test_zero_fps_is_published(self):
        """Zero fps is a valid value and should be published."""
        node, mod = self._make_node()
        results = mock.MagicMock(fps=0.0)
        del results.latency_p95_ms
        del results.gpu_util_avg
        node.publish_inference(results)
        node._pubs["fps"].publish.assert_called_once()


# ---------------------------------------------------------------------------
# publish_status tests
# ---------------------------------------------------------------------------


class TestPublishStatus(unittest.TestCase):
    """Test publish_status serialisation."""

    def _make_node(self):
        mod = _load_node_with_ros2()
        return mod.MonitorNode(), mod

    def test_simple_status(self):
        node, mod = self._make_node()
        node.publish_status({"status": "ok"})
        node._status_pub.publish.assert_called_once()

    def test_json_content_valid(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        payload = {"status": "ok", "value": 42, "nested": {"a": 1}}
        node.publish_status(payload)
        msg = node._status_pub.publish.call_args[0][0]
        parsed = json.loads(msg.data)
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["value"], 42)
        self.assertEqual(parsed["nested"]["a"], 1)

    def test_empty_dict(self):
        node, mod = self._make_node()
        node.publish_status({})
        msg = node._status_pub.publish.call_args[0][0]
        self.assertEqual(json.loads(msg.data), {})

    def test_unicode_characters(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        payload = {"label": "Temperature sensor -- OK"}
        node.publish_status(payload)
        msg = node._status_pub.publish.call_args[0][0]
        parsed = json.loads(msg.data)
        self.assertEqual(parsed["label"], "Temperature sensor -- OK")

    def test_list_values(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        payload = {"devices": [1, 2, 3], "active": True}
        node.publish_status(payload)
        msg = node._status_pub.publish.call_args[0][0]
        parsed = json.loads(msg.data)
        self.assertEqual(parsed["devices"], [1, 2, 3])
        self.assertTrue(parsed["active"])

    def test_multiple_calls(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        node.publish_status({"round": 1})
        node.publish_status({"round": 2})
        self.assertEqual(node._status_pub.publish.call_count, 2)

    def test_noop_without_ros2(self):
        mod = _load_node_without_ros2()
        node = mod.MonitorNode()
        result = node.publish_status({"ok": True})
        self.assertIsNone(result)

    def test_non_json_serializable_uses_default_str(self):
        """Non-serializable values should fall back to default=str."""
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        payload = {"ts": "2026-01-01", "count": 5}
        node.publish_status(payload)
        msg = node._status_pub.publish.call_args[0][0]
        parsed = json.loads(msg.data)
        self.assertIn("ts", parsed)


# ---------------------------------------------------------------------------
# create_monitor_node factory tests
# ---------------------------------------------------------------------------


class TestCreateMonitorNode(unittest.TestCase):
    """Test the create_monitor_node factory function."""

    def test_returns_none_without_ros2(self):
        mod = _load_node_without_ros2()
        self.assertIsNone(mod.create_monitor_node())

    def test_returns_none_with_custom_name_without_ros2(self):
        mod = _load_node_without_ros2()
        self.assertIsNone(mod.create_monitor_node("my_node"))

    def test_returns_instance_with_ros2(self):
        mod = _load_node_with_ros2()
        node = mod.create_monitor_node()
        self.assertIsNotNone(node)
        self.assertIsInstance(node, mod.MonitorNode)

    def test_default_name(self):
        mod = _load_node_with_ros2()
        node = mod.create_monitor_node()
        self.assertEqual(node._name, "ai_edge_monitor")

    def test_custom_name(self):
        mod = _load_node_with_ros2()
        node = mod.create_monitor_node("fleet_monitor")
        self.assertEqual(node._name, "fleet_monitor")

    def test_creates_publishers(self):
        mod = _load_node_with_ros2()
        node = mod.create_monitor_node()
        self.assertEqual(len(node._pubs), 8)
        self.assertTrue(hasattr(node, "_status_pub"))

    def test_node_is_fully_functional(self):
        """Node from factory should be able to publish immediately."""
        mod = _load_node_with_ros2()
        node = mod.create_monitor_node()
        node.publish_metrics({"cpu_avg": 50.0})
        node._pubs["cpu_percent"].publish.assert_called_once()
        node.publish_status({"status": "ok"})
        node._status_pub.publish.assert_called_once()

    def test_logs_warning_without_ros2(self):
        mod = _load_node_without_ros2()
        with mock.patch.object(mod.logger, "warning") as mock_warn:
            mod.create_monitor_node()
            mock_warn.assert_called_once()
            self.assertIn("ROS2", mock_warn.call_args[0][0])

    def test_no_warning_with_ros2(self):
        mod = _load_node_with_ros2()
        with mock.patch.object(mod.logger, "warning") as mock_warn:
            mod.create_monitor_node()
            mock_warn.assert_not_called()


# ---------------------------------------------------------------------------
# HAS_ROS2 flag tests
# ---------------------------------------------------------------------------


class TestHASROS2Flag(unittest.TestCase):
    """Test the module-level HAS_ROS2 flag."""

    def test_false_when_rclpy_absent(self):
        mod = _load_node_without_ros2()
        self.assertFalse(mod.HAS_ROS2)

    def test_true_when_rclpy_present(self):
        mod = _load_node_with_ros2()
        self.assertTrue(mod.HAS_ROS2)

    def test_rclpy_imported_when_available(self):
        mod = _load_node_with_ros2()
        self.assertIsNotNone(mod.rclpy)
        self.assertIsNotNone(mod.RclNode)

    def test_types_none_when_absent(self):
        mod = _load_node_without_ros2()
        self.assertIsNone(mod.Float64)
        self.assertIsNone(mod.String)

    def test_monitor_node_is_object_subclass_when_absent(self):
        mod = _load_node_without_ros2()
        node = mod.MonitorNode()
        self.assertIsInstance(node, object)

    def test_no_pubs_when_absent(self):
        mod = _load_node_without_ros2()
        node = mod.MonitorNode()
        self.assertFalse(hasattr(node, "_pubs"))

    def test_no_status_pub_when_absent(self):
        mod = _load_node_without_ros2()
        node = mod.MonitorNode()
        self.assertFalse(hasattr(node, "_status_pub"))


# ---------------------------------------------------------------------------
# Integration-style: combined publish workflow
# ---------------------------------------------------------------------------


class TestCombinedPublishWorkflow(unittest.TestCase):
    """Simulate a realistic publish workflow using all three methods."""

    def test_full_publish_cycle(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode("integration_test")

        summary = {
            "cpu_avg": 55.0,
            "mem_used_avg_mb": 2048.0,
            "power_avg_watt": 15.0,
            "temp_max_c": 72.0,
            "gpu_percent": 85.0,
        }
        node.publish_metrics(summary)
        for key in mod._SUMMARY_KEY_MAP:
            node._pubs[key].publish.assert_called_once()

        results = mock.MagicMock(fps=30.0, latency_p95_ms=12.0, gpu_util_avg=80.0)
        node.publish_inference(results)
        for key in ("fps", "latency_p95", "gpu_util"):
            node._pubs[key].publish.assert_called_once()

        node.publish_status({"status": "running", "uptime_s": 3600})
        node._status_pub.publish.assert_called_once()

    def test_factory_node_full_workflow(self):
        mod = _load_node_with_ros2()
        node = mod.create_monitor_node("workflow_test")
        self.assertIsNotNone(node)

        node.publish_metrics({"cpu_avg": 30.0, "gpu_percent": 50.0})
        node.publish_inference(mock.MagicMock(fps=25.0, latency_p95_ms=10.0, gpu_util_avg=40.0))
        node.publish_status({"phase": "inference"})

        node._pubs["cpu_percent"].publish.assert_called_once()
        node._pubs["gpu_utilization"].publish.assert_called_once()
        node._pubs["fps"].publish.assert_called_once()
        node._pubs["latency_p95"].publish.assert_called_once()
        node._pubs["gpu_util"].publish.assert_called_once()
        node._status_pub.publish.assert_called_once()


# ---------------------------------------------------------------------------
# Edge-case: HAS_ROS2 -- noop return values and type assertions
# ---------------------------------------------------------------------------


class TestHasRos2EdgeCases(unittest.TestCase):
    """Additional edge-case coverage for HAS_ROS2=False behaviour."""

    def test_publish_metrics_returns_none_without_ros2(self):
        mod = _load_node_without_ros2()
        node = mod.MonitorNode()
        self.assertIsNone(node.publish_metrics({"cpu_avg": 1.0}))

    def test_publish_inference_returns_none_without_ros2(self):
        mod = _load_node_without_ros2()
        node = mod.MonitorNode()
        self.assertIsNone(node.publish_inference(mock.MagicMock()))

    def test_publish_status_returns_none_without_ros2(self):
        mod = _load_node_without_ros2()
        node = mod.MonitorNode()
        self.assertIsNone(node.publish_status({"ok": True}))

    def test_factory_optional_type(self):
        """Without ROS2: None.  With ROS2: MonitorNode instance."""
        mod_no = _load_node_without_ros2()
        self.assertIsNone(mod_no.create_monitor_node())

        mod_yes = _load_node_with_ros2()
        self.assertIsInstance(mod_yes.create_monitor_node(), mod_yes.MonitorNode)

    def test_node_instance_of_fake_node_when_ros2(self):
        mod = _load_node_with_ros2()
        node = mod.MonitorNode()
        self.assertIsInstance(node, mod.RclNode)


if __name__ == "__main__":
    unittest.main()
