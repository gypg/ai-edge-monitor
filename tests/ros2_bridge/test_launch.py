"""Tests for the ROS2 launch file at ros2/launch/monitor.launch.py.

These tests verify the launch file is syntactically valid Python, declares
the expected launch arguments, and configures the Node correctly. They do
NOT require a ROS 2 installation -- the ``launch`` and ``launch_ros``
modules are mocked so the file can be parsed and executed in any environment.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest import mock

# The new launch file lives under ros2/launch/.
LAUNCH_FILE = Path(__file__).resolve().parents[2] / "ros2" / "launch" / "monitor.launch.py"
# Keep backward-compat reference to the old location.
OLD_LAUNCH_FILE = Path(__file__).resolve().parents[2] / "launch" / "monitor.launch.py"


class LaunchFileSyntaxTests(unittest.TestCase):
    """test_launch_file_syntax -- the file must parse as valid Python."""

    def test_launch_file_is_valid_python(self) -> None:
        source = LAUNCH_FILE.read_text(encoding="utf-8")
        # ast.parse raises SyntaxError on invalid Python.
        tree = ast.parse(source, filename=str(LAUNCH_FILE))
        # The file must define generate_launch_description.
        func_names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        self.assertIn(
            "generate_launch_description",
            func_names,
            "launch file must define generate_launch_description()",
        )

    def test_declare_launch_argument_imported(self) -> None:
        """Verify DeclareLaunchArgument is imported."""
        source = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(LAUNCH_FILE))
        import_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    import_names.add(alias.name)
        self.assertIn(
            "DeclareLaunchArgument",
            import_names,
            "DeclareLaunchArgument must be imported for parameterised launches",
        )

    def test_launch_configuration_imported(self) -> None:
        """Verify LaunchConfiguration is imported."""
        source = LAUNCH_FILE.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(LAUNCH_FILE))
        import_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    import_names.add(alias.name)
        self.assertIn(
            "LaunchConfiguration",
            import_names,
            "LaunchConfiguration must be imported for dynamic parameters",
        )

    def test_old_launch_file_still_valid(self) -> None:
        """The original launch/monitor.launch.py must also parse."""
        if not OLD_LAUNCH_FILE.exists():
            self.skipTest("Old launch file not present")
        source = OLD_LAUNCH_FILE.read_text(encoding="utf-8")
        ast.parse(source, filename=str(OLD_LAUNCH_FILE))


def _load_launch_module():
    """Import the launch file with mocked ROS2 launch libraries."""
    fake_launch = mock.MagicMock()
    fake_launch_ros = mock.MagicMock()

    patched = {
        "launch": fake_launch,
        "launch.actions": fake_launch.actions,
        "launch.substitutions": fake_launch.substitutions,
        "launch_ros": fake_launch_ros,
        "launch_ros.actions": fake_launch_ros.actions,
    }
    with mock.patch.dict(sys.modules, patched):
        import importlib.util

        spec = importlib.util.spec_from_file_location("monitor_launch", str(LAUNCH_FILE))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, fake_launch, fake_launch_ros


class LaunchArgumentTests(unittest.TestCase):
    """Verify required launch arguments are declared."""

    def test_generate_launch_description_returns_launch_description(self) -> None:
        module, fake_launch, fake_launch_ros = _load_launch_module()

        self.assertTrue(hasattr(module, "generate_launch_description"))
        result = module.generate_launch_description()
        # It should call LaunchDescription(...)
        fake_launch.LaunchDescription.assert_called_once()
        # It should pass a list containing at least one action.
        call_args = fake_launch.LaunchDescription.call_args
        actions = call_args[0][0] if call_args[0] else []
        self.assertTrue(len(actions) > 0, "launch description must contain actions")

    def test_publish_rate_argument_declared(self) -> None:
        module, fake_launch, _ = _load_launch_module()
        module.generate_launch_description()

        declared_args = {}
        for call in fake_launch.actions.DeclareLaunchArgument.call_args_list:
            arg_name = call[0][0] if call[0] else None
            kw = call[1] if call[1] else {}
            if arg_name:
                declared_args[arg_name] = kw

        self.assertIn(
            "publish_rate",
            declared_args,
            "publish_rate launch argument must be declared",
        )

    def test_node_name_argument_declared(self) -> None:
        module, fake_launch, _ = _load_launch_module()
        module.generate_launch_description()

        declared_args = {}
        for call in fake_launch.actions.DeclareLaunchArgument.call_args_list:
            arg_name = call[0][0] if call[0] else None
            if arg_name:
                declared_args[arg_name] = True

        self.assertIn(
            "node_name",
            declared_args,
            "node_name launch argument must be declared",
        )

    def test_publish_rate_default_is_one(self) -> None:
        module, fake_launch, _ = _load_launch_module()
        module.generate_launch_description()

        for call in fake_launch.actions.DeclareLaunchArgument.call_args_list:
            if call[0] and call[0][0] == "publish_rate":
                default = call[1].get("default_value", call[1].get("default"))
                self.assertEqual(str(default), "1.0", "publish_rate default must be 1.0")
                return
        self.fail("publish_rate DeclareLaunchArgument not found")


class NodeConfigurationTests(unittest.TestCase):
    """Verify the Node() call has the expected configuration."""

    def _get_node_call(self):
        module, _, fake_launch_ros = _load_launch_module()
        module.generate_launch_description()
        self.assertTrue(
            fake_launch_ros.actions.Node.called,
            "Node() must be called in the launch description",
        )
        return fake_launch_ros.actions.Node.call_args

    def test_package_is_ai_edge_monitor(self) -> None:
        kwargs = self._get_node_call()[1]
        self.assertEqual(kwargs["package"], "ai_edge_monitor")

    def test_executable_is_monitor_node(self) -> None:
        kwargs = self._get_node_call()[1]
        self.assertEqual(kwargs["executable"], "monitor_node")

    def test_name_uses_launch_configuration(self) -> None:
        kwargs = self._get_node_call()[1]
        # name should be a LaunchConfiguration substitution, not a string literal.
        # In our mock it becomes a MagicMock from fake_launch.substitutions.
        self.assertIsNotNone(kwargs["name"])

    def test_output_is_screen(self) -> None:
        kwargs = self._get_node_call()[1]
        self.assertEqual(kwargs["output"], "screen")

    def test_parameters_include_publish_rate(self) -> None:
        kwargs = self._get_node_call()[1]
        params = kwargs["parameters"][0]
        self.assertIn("publish_rate", params)


class TopicNameTests(unittest.TestCase):
    """Verify the module source references expected topic names."""

    EXPECTED_TOPICS = [
        "/system/cpu_percent",
        "/system/memory_mb",
        "/system/power_watt",
        "/system/temperature_c",
        "/system/gpu_utilization",
        "/inference/fps",
        "/inference/latency_p95",
        "/inference/gpu_util",
        "/monitor/status",
    ]

    def test_node_module_references_all_topics(self) -> None:
        """The ros2_bridge.node source must mention every expected topic."""
        node_file = Path(__file__).resolve().parents[2] / "src" / "ros2_bridge" / "node.py"
        source = node_file.read_text(encoding="utf-8")
        for topic in self.EXPECTED_TOPICS:
            self.assertIn(
                topic,
                source,
                f"node.py must reference topic {topic}",
            )

    def test_no_unknown_topic_prefixes(self) -> None:
        """Only /system, /inference, /monitor prefixes should appear."""
        node_file = Path(__file__).resolve().parents[2] / "src" / "ros2_bridge" / "node.py"
        source = node_file.read_text(encoding="utf-8")
        valid_prefixes = ("/system/", "/inference/", "/monitor/")
        for line in source.splitlines():
            if '"/' in line:
                import re

                topics = re.findall(r'"/[a-z_]+/[^"]*"', line)
                for topic in topics:
                    topic_stripped = topic.strip('"')
                    self.assertTrue(
                        any(topic_stripped.startswith(p) for p in valid_prefixes),
                        f"Unexpected topic prefix in: {topic_stripped}",
                    )


if __name__ == "__main__":
    unittest.main()
