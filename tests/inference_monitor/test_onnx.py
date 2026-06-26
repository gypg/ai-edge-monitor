"""Tests for the ONNX Runtime profiling bridge."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

import inference_monitor.onnx_bridge as bridge


class TestProfilerStartStop(unittest.TestCase):
    """Verify start/stop_profiling with mocked onnxruntime."""

    def test_start_enables_profiling(self) -> None:
        """start_profiling sets enable_profiling=True on session options."""
        session = mock.MagicMock()
        so = mock.MagicMock()
        session.get_session_options.return_value = so

        profiler = bridge.OnnxProfiler()
        # Temporarily pretend ORT is available
        with mock.patch.object(bridge, "HAS_ORT", True):
            profiler.start_profiling(session)

        self.assertTrue(so.enable_profiling)
        self.assertIn("ort_profile", so.profile_file_prefix)

    def test_stop_returns_parsed_result(self) -> None:
        """stop_profiling parses the JSON output from end_profiling."""
        profile_data = {
            "traceEvents": [
                {"cat": "Node", "name": "Conv_0", "dur": 1000.0},
                {"cat": "Node", "name": "Conv_0", "dur": 2000.0},
                {"cat": "Node", "name": "Relu_1", "dur": 500.0},
            ]
        }
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(tmp_fd)
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(profile_data, fh)

            session = mock.MagicMock()
            so = mock.MagicMock()
            session.get_session_options.return_value = so
            session.end_profiling.return_value = tmp_path

            profiler = bridge.OnnxProfiler()
            with mock.patch.object(bridge, "HAS_ORT", True):
                profiler.start_profiling(session)
                result = profiler.stop_profiling()

            layers = result["layers"]
            self.assertEqual(len(layers), 2)
            # Conv_0 total = 3000us => avg 1.5ms, 2 calls
            conv = next(l for l in layers if l.name == "Conv_0")
            self.assertAlmostEqual(conv.avg_time_ms, 1.5)
            self.assertEqual(conv.calls, 2)
            # Relu_1
            relu = next(l for l in layers if l.name == "Relu_1")
            self.assertAlmostEqual(relu.avg_time_ms, 0.5)
            self.assertEqual(relu.calls, 1)
        finally:
            os.unlink(tmp_path)

    def test_stop_without_start_returns_empty(self) -> None:
        profiler = bridge.OnnxProfiler()
        result = profiler.stop_profiling()
        self.assertEqual(result["layers"], [])
        self.assertEqual(result["raw"], {})


class TestParseProfile(unittest.TestCase):
    """Verify JSON profiling file parsing."""

    def test_parse_valid_file(self) -> None:
        profile_data = {
            "traceEvents": [
                {"cat": "Node", "name": "Gemm_0", "dur": 5000.0},
                {"cat": "Session", "name": "init", "dur": 100.0},
            ]
        }
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(tmp_fd)
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(profile_data, fh)

            result = bridge.OnnxProfiler.parse_profile(tmp_path)

            self.assertEqual(len(result["layers"]), 1)
            layer = result["layers"][0]
            self.assertEqual(layer.name, "Gemm_0")
            self.assertAlmostEqual(layer.avg_time_ms, 5.0)
            self.assertEqual(layer.calls, 1)
        finally:
            os.unlink(tmp_path)

    def test_parse_missing_file_returns_empty(self) -> None:
        result = bridge.OnnxProfiler.parse_profile("/nonexistent/path.json")
        self.assertEqual(result["layers"], [])
        self.assertEqual(result["raw"], {})

    def test_parse_empty_trace_events(self) -> None:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(tmp_fd)
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump({"traceEvents": []}, fh)

            result = bridge.OnnxProfiler.parse_profile(tmp_path)
            self.assertEqual(result["layers"], [])
        finally:
            os.unlink(tmp_path)


class TestImportFallback(unittest.TestCase):
    """Verify graceful handling when onnxruntime is unavailable."""

    def test_profiler_works_without_onnxruntime(self) -> None:
        """Force HAS_ORT to False and verify no crash."""
        with mock.patch.object(bridge, "HAS_ORT", False):
            profiler = bridge.OnnxProfiler()
            profiler.start_profiling(mock.MagicMock())
            result = profiler.stop_profiling()
            self.assertEqual(result["layers"], [])
            self.assertEqual(result["raw"], {})

    def test_parse_profile_static_works_without_ort(self) -> None:
        profile_data = {"traceEvents": [{"cat": "Node", "name": "Add_0", "dur": 200.0}]}
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(tmp_fd)
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(profile_data, fh)

            result = bridge.OnnxProfiler.parse_profile(tmp_path)
            self.assertEqual(len(result["layers"]), 1)
            self.assertEqual(result["layers"][0].name, "Add_0")
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
