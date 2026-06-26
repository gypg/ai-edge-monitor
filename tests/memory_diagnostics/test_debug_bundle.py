"""Tests for memory_diagnostics.debug_bundle."""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from memory_diagnostics.debug_bundle import (  # noqa: E402
    CrashHandler,
    generate_debug_bundle,
)

_PLATFORM = platform.system()
_IS_LINUX = _PLATFORM == "Linux"

# Use the current process PID for testing — it is guaranteed to exist.
_SELF_PID = os.getpid()


# ---------------------------------------------------------------------------
# generate_debug_bundle
# ---------------------------------------------------------------------------


class TestGenerateDebugBundle:
    """Tests for generate_debug_bundle()."""

    def test_bundle_creates_files(self, tmp_path: Path) -> None:
        """All expected files must exist in the bundle directory."""
        bundle = generate_debug_bundle(_SELF_PID, tmp_path)

        assert bundle.is_dir(), "Bundle directory was not created"
        assert bundle.name.startswith("debug_bundle_"), "Unexpected bundle name"

        expected = [
            "proc_status.txt",
            "proc_maps.txt",
            "smaps_rollup.txt",
            "dmesg_tail.txt",
            "diagnosis.json",
        ]
        for fname in expected:
            assert (bundle / fname).is_file(), f"Missing file: {fname}"

    def test_bundle_diagnosis_json(self, tmp_path: Path) -> None:
        """diagnosis.json must contain the expected keys and types."""
        bundle = generate_debug_bundle(_SELF_PID, tmp_path)
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
            assert key in data, f"Missing key in diagnosis.json: {key}"

        assert data["pid"] == _SELF_PID
        assert isinstance(data["files_written"], list)
        assert isinstance(data["warnings"], list)
        assert data["rss_timeline_rows"] == 0
        assert data["gpu_timeline_rows"] == 0
        assert data["bundle_size_bytes"] >= 0

    def test_bundle_with_timelines(self, tmp_path: Path) -> None:
        """RSS and GPU timeline CSVs are written when data is provided."""
        rss = [
            {"ts_ms": 1000, "rss_mb": 120.5},
            {"ts_ms": 2000, "rss_mb": 125.0},
        ]
        gpu = [
            {"ts_ms": 1000, "gpu_mem_mb": 512.0},
            {"ts_ms": 2000, "gpu_mem_mb": 514.0},
        ]
        bundle = generate_debug_bundle(
            _SELF_PID, tmp_path, rss_timeline=rss, gpu_timeline=gpu
        )

        rss_path = bundle / "rss_timeline.csv"
        gpu_path = bundle / "gpu_mem_timeline.csv"
        assert rss_path.is_file(), "rss_timeline.csv was not created"
        assert gpu_path.is_file(), "gpu_mem_timeline.csv was not created"

        # Verify CSV content
        rss_content = rss_path.read_text(encoding="utf-8")
        assert "ts_ms" in rss_content
        assert "120.5" in rss_content

        gpu_content = gpu_path.read_text(encoding="utf-8")
        assert "gpu_mem_mb" in gpu_content
        assert "512.0" in gpu_content

        # Verify diagnosis.json counts
        data = json.loads((bundle / "diagnosis.json").read_text(encoding="utf-8"))
        assert data["rss_timeline_rows"] == 2
        assert data["gpu_timeline_rows"] == 2

    def test_bundle_without_timelines(self, tmp_path: Path) -> None:
        """Bundle generation succeeds without timeline data."""
        bundle = generate_debug_bundle(_SELF_PID, tmp_path)

        assert not (bundle / "rss_timeline.csv").exists()
        assert not (bundle / "gpu_mem_timeline.csv").exists()

        data = json.loads((bundle / "diagnosis.json").read_text(encoding="utf-8"))
        assert data["rss_timeline_rows"] == 0
        assert data["gpu_timeline_rows"] == 0

    def test_bundle_rejects_invalid_pid(self, tmp_path: Path) -> None:
        """Must raise ValueError for non-positive pid."""
        with pytest.raises(ValueError, match="positive integer"):
            generate_debug_bundle(0, tmp_path)
        with pytest.raises(ValueError, match="positive integer"):
            generate_debug_bundle(-1, tmp_path)

    def test_bundle_size_within_limit(self, tmp_path: Path) -> None:
        """Bundle size must stay under 10 MB."""
        bundle = generate_debug_bundle(_SELF_PID, tmp_path)
        data = json.loads((bundle / "diagnosis.json").read_text(encoding="utf-8"))
        assert data["bundle_size_bytes"] < 10 * 1024 * 1024, (
            f"Bundle too large: {data['bundle_size_bytes']} bytes"
        )


# ---------------------------------------------------------------------------
# CrashHandler
# ---------------------------------------------------------------------------


class TestCrashHandler:
    """Tests for CrashHandler install / uninstall."""

    def test_crash_handler_install_uninstall(self) -> None:
        """install() and uninstall() must not raise."""
        handler = CrashHandler()

        # Install — on Windows this logs a warning and no-ops.
        handler.install(_SELF_PID)

        # Second install should be idempotent
        handler.install(_SELF_PID)

        # Uninstall
        handler.uninstall()

        # Double uninstall should be safe
        handler.uninstall()

    @pytest.mark.skipif(not _IS_LINUX, reason="Signal verification only on Linux")
    def test_crash_handler_registers_signals_on_linux(self) -> None:
        """On Linux, signal handlers should be changed after install()."""
        import signal

        handler = CrashHandler()
        handler.install(_SELF_PID)
        try:
            for sig in (signal.SIGSEGV, signal.SIGABRT, signal.SIGTERM):
                current = signal.getsignal(sig)
                assert callable(current), f"Handler for {sig} is not callable"
        finally:
            handler.uninstall()
