"""Tests for the ROS2 launch file.

These tests verify the launch file is syntactically valid Python and has the
expected import structure.  They do NOT require a ROS 2 installation -- the
``launch`` and ``launch_ros`` modules are mocked so the file can be parsed
and executed in any environment.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest import mock


LAUNCH_FILE = Path(__file__).resolve().parents[2] / "launch" / "monitor.launch.py"


class LaunchFileSyntaxTests(unittest.TestCase):
    """test_launch_file_syntax -- the file must parse as valid Python."""

    def test_launch_file_is_valid_python(self) -> None:
        source = LAUNCH_FILE.read_text(encoding="utf-8")
        # ast.parse raises SyntaxError on invalid Python.
        tree = ast.parse(source, filename=str(LAUNCH_FILE))
        # The file must define generate_launch_description.
        func_names = [
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        ]
        self.assertIn(
            "generate_launch_description",
            func_names,
            "launch file must define generate_launch_description()",
        )


class LaunchFileImportTests(unittest.TestCase):
    """test_launch_file_imports -- verify import structure with mocked modules."""

    def test_generate_launch_description_returns_launch_description(self) -> None:
        # Build mock modules so the file can be imported without ROS 2.
        fake_launch = mock.MagicMock()
        fake_launch_ros = mock.MagicMock()

        with mock.patch.dict(
            sys.modules,
            {
                "launch": fake_launch,
                "launch_ros": fake_launch_ros,
                "launch_ros.actions": fake_launch_ros.actions,
            },
        ):
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "monitor_launch", str(LAUNCH_FILE)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # The function must exist and be callable.
            self.assertTrue(hasattr(module, "generate_launch_description"))
            result = module.generate_launch_description()
            # It should call LaunchDescription(...)
            fake_launch.LaunchDescription.assert_called_once()
            # It should pass a list containing at least one Node.
            call_args = fake_launch.LaunchDescription.call_args
            nodes = call_args[0][0] if call_args[0] else []
            self.assertTrue(len(nodes) > 0, "launch description must contain nodes")
            # Each entry should have been created via launch_ros.actions.Node.
            fake_launch_ros.actions.Node.assert_called()

    def test_node_parameters_include_expected_keys(self) -> None:
        """Verify the Node() call receives the three expected parameters."""
        fake_launch = mock.MagicMock()
        fake_launch_ros = mock.MagicMock()

        with mock.patch.dict(
            sys.modules,
            {
                "launch": fake_launch,
                "launch_ros": fake_launch_ros,
                "launch_ros.actions": fake_launch_ros.actions,
            },
        ):
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "monitor_launch_params", str(LAUNCH_FILE)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            module.generate_launch_description()

            node_kwargs = fake_launch_ros.actions.Node.call_args[1]
            self.assertEqual(node_kwargs["package"], "ai_edge_monitor")
            self.assertEqual(node_kwargs["executable"], "monitor_node")
            self.assertEqual(node_kwargs["name"], "ai_edge_monitor")
            params = node_kwargs["parameters"][0]
            self.assertIn("publish_rate", params)
            self.assertIn("power_source", params)
            self.assertIn("include_inference", params)


if __name__ == "__main__":
    unittest.main()
