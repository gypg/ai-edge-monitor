"""Performance profiler — tracks resource usage of monitoring operations.

Measures:
- CPU time (user + system) per operation
- Memory delta (RSS change) per operation
- Wall-clock time per operation
- I/O bytes read/written
- Context switch count (Linux only)

Useful for:
- Proving monitoring overhead is < 3% CPU
- Identifying expensive collector operations
- Benchmarking platform adapters
- Optimizing sampling frequency

Python 3.8+ compatible.  Graceful degradation on Windows (some metrics unavailable).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

# ---------------------------------------------------------------------------
# Constants — sentinel for unavailable metrics on Windows
# ---------------------------------------------------------------------------
UNAVAILABLE: int = -1

# ---------------------------------------------------------------------------
# Platform detection (lightweight, no psutil dependency)
# ---------------------------------------------------------------------------
import os
import sys

_LINUX: bool = sys.platform.startswith("linux")

# Import resource module only on Linux/Unix
if _LINUX or sys.platform != "win32":
    try:
        import resource as _resource
    except ImportError:
        _resource = None  # type: ignore[assignment]
else:
    _resource = None  # type: ignore[assignment]

# Type variable for generic callable profiling
T = TypeVar("T")

# ---------------------------------------------------------------------------
# ProfileSample — immutable snapshot of one operation's cost
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProfileSample:
    """Immutable result of profiling a single operation.

    All time/delta values are measured from ``start()`` to ``stop()``.
    Values of ``UNAVAILABLE`` (-1) indicate the platform could not
    provide that metric (typical on Windows for I/O and ctx switches).
    """

    cpu_user_ms: float
    cpu_sys_ms: float
    wall_ms: float
    rss_delta_kb: int
    io_read_bytes: int
    io_write_bytes: int
    ctx_switches: int
    operation: str = ""

    # -- Convenience properties ------------------------------------------------

    @property
    def cpu_total_ms(self) -> float:
        """Sum of user + system CPU time."""
        return self.cpu_user_ms + self.cpu_sys_ms

    @property
    def cpu_overhead_percent(self) -> float:
        """CPU time as percentage of wall-clock time.

        Returns 0.0 when wall_ms is zero or CPU metrics are unavailable
        (Windows). A result of < 3.0 is the PRD target for monitoring overhead.
        """
        if self.wall_ms <= 0:
            return 0.0
        if self.cpu_user_ms == UNAVAILABLE or self.cpu_sys_ms == UNAVAILABLE:
            return 0.0
        return (self.cpu_total_ms / self.wall_ms) * 100.0

    @property
    def io_total_bytes(self) -> int:
        """Total I/O bytes (read + written).

        Returns ``UNAVAILABLE`` when either component is unavailable.
        """
        if self.io_read_bytes == UNAVAILABLE or self.io_write_bytes == UNAVAILABLE:
            return UNAVAILABLE
        return self.io_read_bytes + self.io_write_bytes


# ---------------------------------------------------------------------------
# /proc/self readers (Linux only, no psutil dependency)
# ---------------------------------------------------------------------------


def _read_proc_self_stat() -> Tuple[float, float, int]:
    """Read CPU times and RSS from /proc/self/stat.

    Returns:
        (cpu_user_sec, cpu_sys_sec, rss_pages)

    Raises:
        OSError: if /proc/self/stat is unreadable.
        ValueError: if the file format is unexpected.
    """
    with open("/proc/self/stat", "r", encoding="ascii") as fh:
        line = fh.readline()

    # Fields after the closing ')' may contain spaces in comm, so find
    # the *last* ')' and parse from there.
    closing = line.rfind(")")
    if closing < 0:
        raise ValueError("unexpected /proc/self/stat format: no closing ')'")
    fields = line[closing + 2 :].split()  # skip ') ' after comm

    # Field indices (0-based after comm):
    #   11 = utime, 12 = stime, 21 = rss
    clk = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    utime = int(fields[11 - 2])  # -2 because comm+state are before split
    stime = int(fields[12 - 2])
    rss_pages = int(fields[21 - 2])

    cpu_user_sec = utime / clk
    cpu_sys_sec = stime / clk
    return cpu_user_sec, cpu_sys_sec, rss_pages


def _read_proc_self_io() -> Tuple[int, int]:
    """Read I/O counters from /proc/self/io.

    Returns:
        (read_bytes, write_bytes)

    Raises:
        OSError: if /proc/self/io is unreadable (may not exist in
                 containers without ``CONFIG_TASK_IO_ACCOUNTING``).
    """
    read_bytes = 0
    write_bytes = 0
    with open("/proc/self/io", "r", encoding="ascii") as fh:
        for line in fh:
            if line.startswith("read_bytes:"):
                read_bytes = int(line.split()[1])
            elif line.startswith("write_bytes:"):
                write_bytes = int(line.split()[1])
    return read_bytes, write_bytes


def _read_context_switches() -> int:
    """Read voluntary context switches from /proc/self/status.

    Returns ``UNAVAILABLE`` if the field is absent.
    """
    try:
        with open("/proc/self/status", "r", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("voluntary_ctxt_switches"):
                    return int(line.split()[1])
    except OSError:
        pass
    return UNAVAILABLE


def _read_rss_kb() -> int:
    """Read current RSS in KiB from /proc/self/statm."""
    try:
        with open("/proc/self/statm", "r", encoding="ascii") as fh:
            parts = fh.readline().split()
        # Field 1 is RSS in pages
        page_size = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
        return int(parts[1]) * (page_size // 1024)
    except (OSError, IndexError, ValueError):
        return UNAVAILABLE


# ---------------------------------------------------------------------------
# OperationProfiler — single-operation profiler
# ---------------------------------------------------------------------------


class OperationProfiler:
    """Profiles a single named operation's resource cost.

    Usage::

        profiler = OperationProfiler("collect_cpu")
        profiler.start()
        # ... do work ...
        sample = profiler.stop()
        print(sample.cpu_overhead_percent)

    Or use the convenience wrapper::

        result, sample = profiler.profile(expensive_fn, arg1, arg2)

    Thread-safety: each ``OperationProfiler`` instance holds mutable
    state (start snapshots) and is **not** thread-safe.  Use one
    instance per call-site or protect with a lock.
    """

    def __init__(self, operation: str = "") -> None:
        self._operation = operation
        self._samples: List[ProfileSample] = []

        # Snapshots taken at start()
        self._started = False
        self._t0_wall: float = 0.0
        self._t0_cpu_user: float = 0.0
        self._t0_cpu_sys: float = 0.0
        self._t0_rss_kb: int = 0
        self._t0_io_read: int = 0
        self._t0_io_write: int = 0
        self._t0_ctx: int = 0

    # -- Snapshot helpers ------------------------------------------------------

    def _snapshot_proc(self) -> None:
        """Capture Linux /proc/self/* metrics."""
        if _LINUX:
            try:
                u, s, _ = _read_proc_self_stat()
                self._t0_cpu_user = u
                self._t0_cpu_sys = s
            except (OSError, ValueError):
                self._t0_cpu_user = 0.0
                self._t0_cpu_sys = 0.0

            try:
                self._t0_io_read, self._t0_io_write = _read_proc_self_io()
            except OSError:
                self._t0_io_read = UNAVAILABLE
                self._t0_io_write = UNAVAILABLE

            self._t0_rss_kb = _read_rss_kb()
            self._t0_ctx = _read_context_switches()
        else:
            # Windows fallback — only wall-clock and rough memory via
            # the resource module (which itself may not exist).
            self._t0_cpu_user = 0.0
            self._t0_cpu_sys = 0.0
            self._t0_io_read = UNAVAILABLE
            self._t0_io_write = UNAVAILABLE
            self._t0_rss_kb = self._snapshot_rss_fallback()
            self._t0_ctx = UNAVAILABLE

    def _snapshot_rss_fallback(self) -> int:
        """Best-effort RSS on non-Linux platforms.

        Uses ``resource.getrusage`` on Unix-likes; returns UNAVAILABLE
        on Windows where neither /proc nor resource module work.
        """
        if _resource is not None:
            try:
                import resource as _ru_mod

                ru = _ru_mod.getrusage(_ru_mod.RUSAGE_SELF)  # type: ignore[attr-defined]
                # ru_maxrss is KiB on Linux, bytes on macOS
                maxrss = ru.ru_maxrss
                if sys.platform == "darwin":
                    maxrss = maxrss // 1024
                return maxrss
            except Exception:
                pass
        return UNAVAILABLE

    def _diff_proc(self) -> ProfileSample:
        """Compute the delta between start() and now."""
        if _LINUX:
            try:
                u_now, s_now, _ = _read_proc_self_stat()
                cpu_user = max(0.0, (u_now - self._t0_cpu_user) * 1000.0)
                cpu_sys = max(0.0, (s_now - self._t0_cpu_sys) * 1000.0)
            except (OSError, ValueError):
                cpu_user = UNAVAILABLE
                cpu_sys = UNAVAILABLE

            rss_now = _read_rss_kb()
            if self._t0_rss_kb == UNAVAILABLE or rss_now == UNAVAILABLE:
                rss_delta = UNAVAILABLE
            else:
                rss_delta = rss_now - self._t0_rss_kb

            try:
                io_r_now, io_w_now = _read_proc_self_io()
                io_read = (
                    io_r_now - self._t0_io_read if self._t0_io_read != UNAVAILABLE else UNAVAILABLE
                )
                io_write = (
                    io_w_now - self._t0_io_write
                    if self._t0_io_write != UNAVAILABLE
                    else UNAVAILABLE
                )
            except OSError:
                io_read = UNAVAILABLE
                io_write = UNAVAILABLE

            ctx_now = _read_context_switches()
            ctx = (
                max(0, ctx_now - self._t0_ctx)
                if self._t0_ctx != UNAVAILABLE and ctx_now != UNAVAILABLE
                else UNAVAILABLE
            )
        else:
            cpu_user = UNAVAILABLE
            cpu_sys = UNAVAILABLE
            rss_delta = UNAVAILABLE
            io_read = UNAVAILABLE
            io_write = UNAVAILABLE
            ctx = UNAVAILABLE

        wall = (time.perf_counter() - self._t0_wall) * 1000.0

        return ProfileSample(
            cpu_user_ms=cpu_user,
            cpu_sys_ms=cpu_sys,
            wall_ms=wall,
            rss_delta_kb=rss_delta,
            io_read_bytes=io_read,
            io_write_bytes=io_write,
            ctx_switches=ctx,
            operation=self._operation,
        )

    # -- Public API ------------------------------------------------------------

    def start(self) -> None:
        """Begin profiling.  Must be paired with a later ``stop()``."""
        self._snapshot_proc()
        self._t0_wall = time.perf_counter()
        self._started = True

    def stop(self) -> ProfileSample:
        """Stop profiling and return the sample.

        Raises:
            RuntimeError: if ``start()`` was not called first.
        """
        if not self._started:
            raise RuntimeError("OperationProfiler.stop() called without start()")
        sample = self._diff_proc()
        self._started = False
        self._samples.append(sample)
        return sample

    def profile(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> Tuple[T, ProfileSample]:
        """Profile a callable.

        Returns:
            A ``(result, sample)`` tuple where *result* is the return
            value of *fn* and *sample* is the profiling data.
        """
        self.start()
        try:
            result = fn(*args, **kwargs)
        finally:
            sample = self.stop()
        return result, sample

    @property
    def samples(self) -> Tuple[ProfileSample, ...]:
        """All collected samples (read-only view)."""
        return tuple(self._samples)

    def summary(self) -> Dict[str, Any]:
        """Aggregate statistics across all collected samples.

        Returns a dict with min/max/mean/total for each metric,
        plus sample count and the operation name.
        """
        if not self._samples:
            return {"operation": self._operation, "count": 0}

        n = len(self._samples)
        result: Dict[str, Any] = {"operation": self._operation, "count": n}

        for attr in (
            "cpu_user_ms",
            "cpu_sys_ms",
            "wall_ms",
            "rss_delta_kb",
            "io_read_bytes",
            "io_write_bytes",
            "ctx_switches",
        ):
            vals = [getattr(s, attr) for s in self._samples]
            # Filter out UNAVAILABLE for numeric aggregation
            numeric = [v for v in vals if v != UNAVAILABLE]
            if not numeric:
                result[f"{attr}_min"] = UNAVAILABLE
                result[f"{attr}_max"] = UNAVAILABLE
                result[f"{attr}_mean"] = UNAVAILABLE
                result[f"{attr}_total"] = UNAVAILABLE
            else:
                result[f"{attr}_min"] = min(numeric)
                result[f"{attr}_max"] = max(numeric)
                result[f"{attr}_mean"] = sum(numeric) / len(numeric)
                result[f"{attr}_total"] = sum(numeric)

        # Derived metric: average overhead %
        # Only include samples where wall > 0 and CPU is available
        valid = [
            s
            for s in self._samples
            if s.wall_ms > 0 and s.cpu_user_ms != UNAVAILABLE and s.cpu_sys_ms != UNAVAILABLE
        ]
        if valid:
            total_cpu = sum(s.cpu_total_ms for s in valid)
            total_wall = sum(s.wall_ms for s in valid)
            result["avg_overhead_percent"] = (total_cpu / total_wall) * 100.0
        else:
            result["avg_overhead_percent"] = 0.0

        return result

    def reset(self) -> None:
        """Clear all collected samples."""
        self._samples.clear()


# ---------------------------------------------------------------------------
# CgroupProfiler — container resource profiling via /sys/fs/cgroup
# ---------------------------------------------------------------------------


class CgroupProfiler:
    """Reads cgroup v1/v2 resource limits and current usage.

    Useful for proving the monitoring process stays within its
    container resource budget.  On non-Linux hosts or when cgroup
    filesystem is absent, all reads return ``UNAVAILABLE``.

    Supports both cgroup v1 (``/sys/fs/cgroup/cpuacct``,
    ``/sys/fs/cgroup/memory``) and cgroup v2
    (``/sys/fs/cgroup/system.slice/...``) hierarchies.
    """

    def __init__(self, cgroup_path: Optional[str] = None) -> None:
        self._cgroup_path = cgroup_path
        self._is_v2 = self._detect_cgroup_version()

    @staticmethod
    def _detect_cgroup_version() -> bool:
        """Detect cgroup v2 by checking for the unified hierarchy marker."""
        if not _LINUX:
            return False
        try:
            return os.path.isfile("/sys/fs/cgroup/cgroup.controllers")
        except OSError:
            return False

    # -- cgroup v1 readers -----------------------------------------------------

    @staticmethod
    def _read_v1_cpu_usage() -> int:
        """Read CPU usage in nanoseconds from cgroup v1."""
        try:
            with open("/sys/fs/cgroup/cpuacct/cpuacct.usage", "r", encoding="ascii") as fh:
                return int(fh.read().strip())
        except OSError:
            return UNAVAILABLE

    @staticmethod
    def _read_v1_cpu_limit() -> int:
        """Read CPU quota period from cgroup v1.

        Returns the quota in microseconds per period, or UNAVAILABLE.
        """
        try:
            with open("/sys/fs/cgroup/cpuacct/cpu.cfs_quota_us", "r", encoding="ascii") as fh:
                quota = int(fh.read().strip())
            if quota < 0:
                return UNAVAILABLE  # -1 means unlimited
            return quota
        except OSError:
            return UNAVAILABLE

    @staticmethod
    def _read_v1_memory_usage() -> int:
        """Read current memory usage in bytes from cgroup v1."""
        try:
            with open("/sys/fs/cgroup/memory/memory.usage_in_bytes", "r", encoding="ascii") as fh:
                return int(fh.read().strip())
        except OSError:
            return UNAVAILABLE

    @staticmethod
    def _read_v1_memory_limit() -> int:
        """Read memory limit in bytes from cgroup v1."""
        try:
            with open("/sys/fs/cgroup/memory/memory.limit_in_bytes", "r", encoding="ascii") as fh:
                limit = int(fh.read().strip())
            # A very large limit (>= 2^62) means effectively unlimited
            if limit >= (1 << 62):
                return UNAVAILABLE
            return limit
        except OSError:
            return UNAVAILABLE

    # -- cgroup v2 readers -----------------------------------------------------

    def _v2_base_path(self) -> Optional[str]:
        """Resolve the cgroup v2 base path for this process."""
        if self._cgroup_path:
            return self._cgroup_path
        if not _LINUX:
            return None
        # Read own cgroup membership from /proc/self/cgroup
        try:
            with open("/proc/self/cgroup", "r", encoding="ascii") as fh:
                for line in fh:
                    parts = line.strip().split(":")
                    if len(parts) >= 3 and parts[0] == "0" and parts[1] == "":
                        # v2 unified hierarchy: "0::<path>"
                        relative = parts[2]
                        return os.path.join("/sys/fs/cgroup", relative.lstrip("/"))
        except OSError:
            pass
        # Fallback to root cgroup
        return "/sys/fs/cgroup"

    @staticmethod
    def _read_v2_cpu_usage() -> int:
        """Read CPU usage from cgroup v2 cpu.stat."""
        try:
            with open("/sys/fs/cgroup/cpu.stat", "r", encoding="ascii") as fh:
                for line in fh:
                    if line.startswith("usage_usec "):
                        return int(line.split()[1]) * 1000  # usec -> nsec
        except OSError:
            pass
        return UNAVAILABLE

    @staticmethod
    def _read_v2_memory_usage() -> int:
        """Read current memory usage in bytes from cgroup v2."""
        try:
            with open("/sys/fs/cgroup/memory.current", "r", encoding="ascii") as fh:
                return int(fh.read().strip())
        except OSError:
            return UNAVAILABLE

    @staticmethod
    def _read_v2_memory_limit() -> int:
        """Read memory limit from cgroup v2 memory.max."""
        try:
            with open("/sys/fs/cgroup/memory.max", "r", encoding="ascii") as fh:
                raw = fh.read().strip()
            if raw == "max":
                return UNAVAILABLE  # unlimited
            return int(raw)
        except OSError:
            return UNAVAILABLE

    # -- Public API ------------------------------------------------------------

    def read_cpu_usage_ns(self) -> int:
        """Return cumulative CPU usage in nanoseconds.

        Returns ``UNAVAILABLE`` on non-Linux or when cgroup files are
        absent.
        """
        if not _LINUX:
            return UNAVAILABLE
        if self._is_v2:
            return self._read_v2_cpu_usage()
        return self._read_v1_cpu_usage()

    def read_cpu_quota_us(self) -> int:
        """Return CFS CPU quota in microseconds per period.

        Returns ``UNAVAILABLE`` when unlimited or on unsupported hosts.
        """
        if not _LINUX:
            return UNAVAILABLE
        if self._is_v2:
            # cgroup v2 uses cpu.max: "$MAX $PERIOD"
            try:
                with open("/sys/fs/cgroup/cpu.max", "r", encoding="ascii") as fh:
                    parts = fh.read().strip().split()
                if parts[0] == "max":
                    return UNAVAILABLE
                return int(parts[0])  # quota in usec
            except OSError:
                return UNAVAILABLE
        return self._read_v1_cpu_limit()

    def read_memory_usage_bytes(self) -> int:
        """Return current cgroup memory usage in bytes."""
        if not _LINUX:
            return UNAVAILABLE
        if self._is_v2:
            return self._read_v2_memory_usage()
        return self._read_v1_memory_usage()

    def read_memory_limit_bytes(self) -> int:
        """Return cgroup memory limit in bytes."""
        if not _LINUX:
            return UNAVAILABLE
        if self._is_v2:
            return self._read_v2_memory_limit()
        return self._read_v1_memory_limit()

    def snapshot(self) -> Dict[str, Any]:
        """Return a combined cgroup resource snapshot.

        Keys:
            ``cpu_usage_ns``, ``cpu_quota_us``, ``memory_usage_bytes``,
            ``memory_limit_bytes``, ``cgroup_version``.
        """
        return {
            "cpu_usage_ns": self.read_cpu_usage_ns(),
            "cpu_quota_us": self.read_cpu_quota_us(),
            "memory_usage_bytes": self.read_memory_usage_bytes(),
            "memory_limit_bytes": self.read_memory_limit_bytes(),
            "cgroup_version": "v2" if self._is_v2 else "v1",
        }


# ---------------------------------------------------------------------------
# MultiOperationProfiler — profiles many named operations
# ---------------------------------------------------------------------------


class MultiOperationProfiler:
    """Tracks multiple named operations independently.

    Usage::

        multi = MultiOperationProfiler()
        with multi.measure("collect_cpu"):
            collect_cpu()
        with multi.measure("collect_mem"):
            collect_mem()
        report = multi.report()

    Each operation gets its own ``OperationProfiler`` instance, so
    samples are isolated per operation name.
    """

    def __init__(self) -> None:
        self._profilers: Dict[str, OperationProfiler] = {}

    def _get_or_create(self, operation: str) -> OperationProfiler:
        if operation not in self._profilers:
            self._profilers[operation] = OperationProfiler(operation)
        return self._profilers[operation]

    def start(self, operation: str) -> None:
        """Start profiling *operation*."""
        self._get_or_create(operation).start()

    def stop(self, operation: str) -> ProfileSample:
        """Stop profiling *operation* and return the sample.

        Raises:
            KeyError: if *operation* was never started.
            RuntimeError: if ``start()`` was not called for this operation.
        """
        if operation not in self._profilers:
            raise KeyError(f"no profiler for operation {operation!r}")
        return self._profilers[operation].stop()

    class _MeasureContext:
        """Context manager returned by ``MultiOperationProfiler.measure()``."""

        def __init__(self, profiler: MultiOperationProfiler, operation: str) -> None:
            self._profiler = profiler
            self._operation = operation
            self.sample: Optional[ProfileSample] = None

        def __enter__(self) -> "MultiOperationProfiler._MeasureContext":
            self._profiler.start(self._operation)
            return self

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            self.sample = self._profiler.stop(self._operation)

    def measure(self, operation: str) -> _MeasureContext:
        """Return a context manager that profiles *operation*.

        The resulting sample is stored in ``context.sample`` after the
        block exits::

            with multi.measure("scan") as ctx:
                do_scan()
            print(ctx.sample.wall_ms)
        """
        return self._MeasureContext(self, operation)

    def profile(
        self, operation: str, fn: Callable[..., T], *args: Any, **kwargs: Any
    ) -> Tuple[T, ProfileSample]:
        """Profile a callable under the given *operation* name.

        Returns ``(result, sample)``.
        """
        prof = self._get_or_create(operation)
        return prof.profile(fn, *args, **kwargs)

    def get_profiler(self, operation: str) -> Optional[OperationProfiler]:
        """Return the underlying profiler for *operation*, or None."""
        return self._profilers.get(operation)

    def operations(self) -> Tuple[str, ...]:
        """Return the names of all tracked operations."""
        return tuple(self._profilers.keys())

    def report(self) -> Dict[str, Dict[str, Any]]:
        """Return per-operation summaries.

        Returns a dict keyed by operation name whose values are the
        ``summary()`` dicts from each underlying profiler.
        """
        return {name: prof.summary() for name, prof in self._profilers.items()}

    def all_samples(self) -> Dict[str, Tuple[ProfileSample, ...]]:
        """Return all collected samples grouped by operation name."""
        return {name: prof.samples for name, prof in self._profilers.items()}

    def reset(self) -> None:
        """Clear all samples for all operations."""
        for prof in self._profilers.values():
            prof.reset()

    def reset_operation(self, operation: str) -> None:
        """Clear samples for a single operation.

        Raises:
            KeyError: if *operation* was never profiled.
        """
        if operation not in self._profilers:
            raise KeyError(f"no profiler for operation {operation!r}")
        self._profilers[operation].reset()
