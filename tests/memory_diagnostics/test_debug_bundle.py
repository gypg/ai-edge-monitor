"""Tests for memory_diagnostics.debug_bundle."""

from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory_diagnostics.debug_bundle import (  # noqa: E402
    CrashHandler,
    generate_debug_bundle,
)

_PLATFORM = platform.system()
_IS_LINUX = _PLATFORM == "Linux"

# Use the current process PID for testing -- it is guaranteed to exist.
_SELF_PID = os.getpid()


# ---------------------------------------------------------------------------
# generate_debug_bundle
# ---------------------------------------------------------------------------


class TestGenerateDebugBundle(unittest.TestCase):
    """Tests for generate_debug_bundle()."""

    def test_bundle_creates_files(self) -> None:
        """All expected files must exist in the bundle directory."""
        with tempfile.TemporaryDirectory() as tmp_path:
            bundle = generate_debug_bundle(_SELF_PID, Path(tmp_path))

            self.assertTrue(bundle.is_dir(), "Bundle directory was not created")
            self.assertTrue(bundle.name.startswith("debug_bundle_"), "Unexpected bundle name")

            expected = [
                "proc_status.txt",
                "proc_maps.txt",
                "smaps_rollup.txt",
                "dmesg_tail.txt",
                "diagnosis.json",
            ]
            for fname in expected:
                self.assertTrue((bundle / fname).is_file(), f"Missing file: {fname}")

    def test_bundle_diagnosis_json(self) -> None:
        """diagnosis.json must contain the expected keys and types."""
        with tempfile.TemporaryDirectory() as tmp_path:
            bundle = generate_debug_bundle(_SELF_PID, Path(tmp_path))
            data = json.loads((bundle / "diagnosis.json").read_text(encoding="utf-8"))

            # Required keys
            for key in (
                "pid",
                "platform",
                "generated_at_utc",
                "generation_time_ms",
                "files_written",
                "rss_timeline_rows",
                "gpu_timeline_rows",
                "warnings",
                "bundle_size_bytes",
            ):
                self.assertIn(key, data, f"Missing key in diagnosis.json: {key}")

            self.assertEqual(data["pid"], _SELF_PID)
            self.assertIsInstance(data["files_written"], list)
            self.assertIsInstance(data["warnings"], list)
            self.assertEqual(data["rss_timeline_rows"], 0)
            self.assertEqual(data["gpu_timeline_rows"], 0)
            self.assertGreaterEqual(data["bundle_size_bytes"], 0)

    def test_bundle_with_timelines(self) -> None:
        """RSS and GPU timeline CSVs are written when data is provided."""
        rss = [
            {"ts_ms": 1000, "rss_mb": 120.5},
            {"ts_ms": 2000, "rss_mb": 125.0},
        ]
        gpu = [
            {"ts_ms": 1000, "gpu_mem_mb": 512.0},
            {"ts_ms": 2000, "gpu_mem_mb": 514.0},
        ]
        with tempfile.TemporaryDirectory() as tmp_path:
            bundle = generate_debug_bundle(
                _SELF_PID, Path(tmp_path), rss_timeline=rss, gpu_timeline=gpu
            )

            rss_path = bundle / "rss_timeline.csv"
            gpu_path = bundle / "gpu_mem_timeline.csv"
            self.assertTrue(rss_path.is_file(), "rss_timeline.csv was not created")
            self.assertTrue(gpu_path.is_file(), "gpu_mem_timeline.csv was not created")

            # Verify CSV content
            rss_content = rss_path.read_text(encoding="utf-8")
            self.assertIn("ts_ms", rss_content)
            self.assertIn("120.5", rss_content)

            gpu_content = gpu_path.read_text(encoding="utf-8")
            self.assertIn("gpu_mem_mb", gpu_content)
            self.assertIn("512.0", gpu_content)

            # Verify diagnosis.json counts
            data = json.loads((bundle / "diagnosis.json").read_text(encoding="utf-8"))
            self.assertEqual(data["rss_timeline_rows"], 2)
            self.assertEqual(data["gpu_timeline_rows"], 2)

    def test_bundle_without_timelines(self) -> None:
        """Bundle generation succeeds without timeline data."""
        with tempfile.TemporaryDirectory() as tmp_path:
            bundle = generate_debug_bundle(_SELF_PID, Path(tmp_path))

            self.assertFalse((bundle / "rss_timeline.csv").exists())
            self.assertFalse((bundle / "gpu_mem_timeline.csv").exists())

            data = json.loads((bundle / "diagnosis.json").read_text(encoding="utf-8"))
            self.assertEqual(data["rss_timeline_rows"], 0)
            self.assertEqual(data["gpu_timeline_rows"], 0)

    def test_bundle_rejects_invalid_pid(self) -> None:
        """Must raise ValueError for non-positive pid."""
        with tempfile.TemporaryDirectory() as tmp_path:
            with self.assertRaises(ValueError) as cm:
                generate_debug_bundle(0, Path(tmp_path))
            self.assertIn("positive integer", str(cm.exception))

            with self.assertRaises(ValueError) as cm:
                generate_debug_bundle(-1, Path(tmp_path))
            self.assertIn("positive integer", str(cm.exception))

    def test_bundle_size_within_limit(self) -> None:
        """Bundle size must stay under 10 MB."""
        with tempfile.TemporaryDirectory() as tmp_path:
            bundle = generate_debug_bundle(_SELF_PID, Path(tmp_path))
            data = json.loads((bundle / "diagnosis.json").read_text(encoding="utf-8"))
            self.assertLess(data["bundle_size_bytes"], 10 * 1024 * 1024,
                            f"Bundle too large: {data['bundle_size_bytes']} bytes")


# ---------------------------------------------------------------------------
# CrashHandler
# ---------------------------------------------------------------------------


class TestCrashHandler(unittest.TestCase):
    """Tests for CrashHandler install / uninstall."""

    def test_crash_handler_install_uninstall(self) -> None:
        """install() and uninstall() must not raise."""
        handler = CrashHandler()

        # Install -- on Windows this logs a warning and no-ops.
        handler.install(_SELF_PID)

        # Second install should be idempotent
        handler.install(_SELF_PID)

        # Uninstall
        handler.uninstall()

        # Double uninstall should be safe
        handler.uninstall()

    @unittest.skipUnless(_IS_LINUX, "Signal verification only on Linux")
    def test_crash_handler_registers_signals_on_linux(self) -> None:
        """On Linux, signal handlers should be changed after install()."""
        import signal

        handler = CrashHandler()
        handler.install(_SELF_PID)
        try:
            for sig in (signal.SIGSEGV, signal.SIGABRT, signal.SIGTERM):
                current = signal.getsignal(sig)
                self.assertTrue(callable(current), f"Handler for {sig} is not callable")
        finally:
            handler.uninstall()


if __name__ == "__main__":
    unittest.main()
