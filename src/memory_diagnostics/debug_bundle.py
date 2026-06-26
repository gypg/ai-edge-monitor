"""debug_bundle — Crash-time diagnostic bundle generator.

Collects process state, memory maps, kernel messages, and optional
timeline CSVs into a timestamped directory for offline analysis.

Platform notes:
    - Linux: reads real /proc/<pid>/status, /proc/<pid>/maps,
      /proc/<pid>/smaps_rollup, and dmesg.
    - Windows/macOS: writes placeholder files with a diagnostic note
      so the bundle structure is always consistent.

Constraints (spec §4.4):
    - Generation time < 1 s
    - Total bundle size < 10 MB
    - No secrets or credentials written
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import platform
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("memory_diagnostics.debug_bundle")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_BUNDLE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
_PLATFORM = platform.system()
_IS_LINUX = _PLATFORM == "Linux"

_EXPECTED_FILES = (
    "proc_status.txt",
    "proc_maps.txt",
    "smaps_rollup.txt",
    "dmesg_tail.txt",
    "diagnosis.json",
)

_OPTIONAL_TIMELINE_FILES = (
    "rss_timeline.csv",
    "gpu_mem_timeline.csv",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_proc_file(pid: int, name: str) -> str:
    """Read /proc/<pid>/<name>, returning a placeholder on non-Linux."""
    path = f"/proc/{pid}/{name}"
    try:
        with open(path, "r", errors="replace") as fh:
            return fh.read()
    except FileNotFoundError:
        return f"[unavailable] Process {pid} not found at {path}"
    except PermissionError:
        return f"[unavailable] Permission denied reading {path}"
    except OSError as exc:
        return f"[unavailable] OS error reading {path}: {exc}"


def _read_dmesg_tail() -> str:
    """Return last 100 lines of dmesg, or a placeholder on non-Linux."""
    if not _IS_LINUX:
        return "[unavailable] dmesg is only accessible on Linux"
    try:
        import subprocess

        result = subprocess.run(
            ["dmesg", "--time-format=iso"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = result.stdout.strip().splitlines()
        return "\n".join(lines[-100:]) if lines else "[empty] dmesg returned no output"
    except FileNotFoundError:
        return "[unavailable] dmesg command not found"
    except subprocess.TimeoutExpired:
        return "[unavailable] dmesg timed out after 5s"
    except OSError as exc:
        return f"[unavailable] OS error running dmesg: {exc}"


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    """Write a list of dicts as CSV.  No-ops when *rows* is empty."""
    if not rows:
        return
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


def _dir_size_bytes(path: Path) -> int:
    """Recursive directory size."""
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_debug_bundle(
    pid: int,
    output_dir: Path,
    rss_timeline: Optional[List[Dict[str, Any]]] = None,
    gpu_timeline: Optional[List[Dict[str, Any]]] = None,
) -> Path:
    """Generate a diagnostic bundle for *pid* under *output_dir*.

    Parameters
    ----------
    pid:
        Target process ID.
    output_dir:
        Parent directory in which the bundle folder is created.
    rss_timeline:
        Optional list of dicts to write as ``rss_timeline.csv``.
    gpu_timeline:
        Optional list of dicts to write as ``gpu_mem_timeline.csv``.

    Returns
    -------
    Path
        Absolute path to the newly created bundle directory.

    Raises
    ------
    ValueError
        If *pid* is not a positive integer.
    OSError
        If the bundle directory cannot be created.
    """
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError(f"pid must be a positive integer, got {pid!r}")

    start = time.monotonic()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle_name = f"debug_bundle_{pid}_{timestamp}"
    bundle_dir = (output_dir / bundle_name).resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # -- 1. /proc status --------------------------------------------------
    (bundle_dir / "proc_status.txt").write_text(
        _read_proc_file(pid, "status"), encoding="utf-8"
    )

    # -- 2. /proc maps -----------------------------------------------------
    (bundle_dir / "proc_maps.txt").write_text(
        _read_proc_file(pid, "maps"), encoding="utf-8"
    )

    # -- 3. smaps rollup ---------------------------------------------------
    (bundle_dir / "smaps_rollup.txt").write_text(
        _read_proc_file(pid, "smaps_rollup"), encoding="utf-8"
    )

    # -- 4. dmesg tail -----------------------------------------------------
    (bundle_dir / "dmesg_tail.txt").write_text(
        _read_dmesg_tail(), encoding="utf-8"
    )

    # -- 5. RSS timeline CSV -----------------------------------------------
    if rss_timeline:
        _write_csv(bundle_dir / "rss_timeline.csv", rss_timeline)

    # -- 6. GPU mem timeline CSV -------------------------------------------
    if gpu_timeline:
        _write_csv(bundle_dir / "gpu_mem_timeline.csv", gpu_timeline)

    # -- 7. Diagnosis summary JSON -----------------------------------------
    elapsed_ms = (time.monotonic() - start) * 1000
    diagnosis: Dict[str, Any] = {
        "pid": pid,
        "platform": _PLATFORM,
        "generated_at_utc": timestamp,
        "generation_time_ms": round(elapsed_ms, 2),
        "files_written": sorted(f.name for f in bundle_dir.iterdir()),
        "rss_timeline_rows": len(rss_timeline) if rss_timeline else 0,
        "gpu_timeline_rows": len(gpu_timeline) if gpu_timeline else 0,
        "warnings": [],
    }

    # Size constraint check
    size_bytes = _dir_size_bytes(bundle_dir)
    if size_bytes > _MAX_BUNDLE_SIZE_BYTES:
        warning = (
            f"Bundle size ({size_bytes} bytes) exceeds {_MAX_BUNDLE_SIZE_BYTES} bytes"
        )
        LOG.warning(warning)
        diagnosis["warnings"].append(warning)

    diagnosis["bundle_size_bytes"] = size_bytes
    (bundle_dir / "diagnosis.json").write_text(
        json.dumps(diagnosis, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    LOG.info(
        "Debug bundle generated: %s (%d bytes, %.1f ms)",
        bundle_dir,
        size_bytes,
        elapsed_ms,
    )
    return bundle_dir


# ---------------------------------------------------------------------------
# CrashHandler
# ---------------------------------------------------------------------------

# Signals we want to catch on Linux
_LINUX_SIGNALS = (signal.SIGSEGV, signal.SIGABRT, signal.SIGTERM)


class CrashHandler:
    """Catch fatal signals and generate a debug bundle before dying.

    On non-Linux platforms the handler is a no-op that logs a WARNING.
    """

    def __init__(self) -> None:
        self._pid: Optional[int] = None
        self._original_handlers: Dict[int, Any] = {}
        self._installed = False

    # -- public API -------------------------------------------------------

    def install(self, pid: int) -> None:
        """Register signal handlers for *pid*.

        On Linux this replaces the handlers for SIGSEGV, SIGABRT, and
        SIGTERM.  On other platforms it logs a warning and returns.
        """
        if self._installed:
            LOG.debug("CrashHandler already installed; skipping")
            return

        self._pid = pid

        if not _IS_LINUX:
            LOG.warning(
                "Signal handling is limited on %s; CrashHandler is a no-op",
                _PLATFORM,
            )
            return

        for sig in _LINUX_SIGNALS:
            self._original_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, self._make_handler(sig))

        self._installed = True
        LOG.info("CrashHandler installed for pid %d", pid)

    def uninstall(self) -> None:
        """Restore original signal handlers."""
        if not self._installed:
            return

        if not _IS_LINUX:
            return

        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)

        self._original_handlers.clear()
        self._installed = False
        LOG.info("CrashHandler uninstalled")

    # -- internals --------------------------------------------------------

    def _make_handler(self, sig: int):
        """Create a closure for the given signal number."""
        pid = self._pid  # capture for closure

        def _handler(signum, frame):
            LOG.warning("Caught signal %s for pid %s; generating bundle", signum, pid)
            try:
                bundle_dir = generate_debug_bundle(pid, Path.cwd())
                LOG.warning("Crash bundle written to %s", bundle_dir)
            except Exception:
                LOG.exception("Failed to generate crash bundle for signal %s", signum)

            # Restore original handler and re-raise the signal so the
            # default behaviour (core dump / termination) still occurs.
            original = self._original_handlers.get(sig)
            if original is not None:
                signal.signal(sig, original)
            signal.raise_signal(sig)

        return _handler
