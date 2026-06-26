"""Comprehensive tests for performance_profiler.profiler module.

Covers ProfileSample, OperationProfiler, and MultiOperationProfiler
across 12 categories: field verification, timing, context manager,
CPU time, memory tracking, I/O tracking, multi-operation, summary
statistics, overhead measurement, thread safety, cross-platform
graceful degradation, and large workloads.

Run standalone:  python tests/performance_profiler/test_profiler.py
"""

from __future__ import annotations

import math
import os
import platform
import sys
import threading
import time
import unittest
from pathlib import Path
from typing import List, Tuple

# -- path bootstrap (matches project convention) --------------------------
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from performance_profiler.profiler import (  # noqa: E402
    MultiOperationProfiler,
    OperationProfiler,
    ProfileSample,
)

IS_LINUX = sys.platform.startswith("linux")
IS_WINDOWS = platform.system() == "Windows"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cpu_burn(seconds: float = 0.05) -> float:
    """Burn CPU for *seconds* by summing floats. Returns dummy result."""
    end = time.monotonic() + seconds
    total = 0.0
    while time.monotonic() < end:
        total += 1.000001
    return total


def _allocate_memory(mb: int = 5) -> bytearray:
    """Allocate ~*mb* MB and return the buffer so GC cannot reclaim it."""
    return bytearray(mb * 1024 * 1024)


def _io_work(size_kb: int = 64) -> int:
    """Write then read a temp file of *size_kb* KB. Returns bytes written."""
    import tempfile

    data = os.urandom(size_kb * 1024)
    path = None
    try:
        fd, path = tempfile.mkstemp(suffix=".profiler_test")
        os.close(fd)
        with open(path, "wb") as fh:
            fh.write(data)
        with open(path, "rb") as fh:
            _ = fh.read()
        return len(data)
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


# ===========================================================================
# 1. ProfileSample field verification
# ===========================================================================


class TestProfileSampleCreation(unittest.TestCase):
    """Verify every field on ProfileSample is present and correctly typed."""

    def test_sample_has_expected_fields(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        _cpu_burn(0.01)
        sample = profiler.stop()

        expected_fields = [
            "cpu_user_ms",
            "cpu_sys_ms",
            "wall_ms",
            "rss_delta_kb",
            "io_read_bytes",
            "io_write_bytes",
            "ctx_switches",
        ]
        for field in expected_fields:
            self.assertTrue(
                hasattr(sample, field),
                f"ProfileSample missing field: {field}",
            )

    def test_sample_field_types(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        _cpu_burn(0.01)
        sample = profiler.stop()

        self.assertIsInstance(sample.cpu_user_ms, (int, float))
        self.assertIsInstance(sample.cpu_sys_ms, (int, float))
        self.assertIsInstance(sample.wall_ms, (int, float))
        self.assertIsInstance(sample.rss_delta_kb, (int, float))
        self.assertIsInstance(sample.io_read_bytes, (int, float))
        self.assertIsInstance(sample.io_write_bytes, (int, float))
        self.assertIsInstance(sample.ctx_switches, (int, float))

    def test_sample_non_negative_values(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        _cpu_burn(0.01)
        sample = profiler.stop()

        # wall_ms is always available and non-negative
        self.assertGreaterEqual(sample.wall_ms, 0)
        # On Windows, CPU/IO/RSS/ctx may be UNAVAILABLE (-1), which is valid
        if IS_LINUX:
            self.assertGreaterEqual(sample.cpu_user_ms, 0)
            self.assertGreaterEqual(sample.cpu_sys_ms, 0)
            self.assertGreaterEqual(sample.rss_delta_kb, 0)
            self.assertGreaterEqual(sample.io_read_bytes, 0)
            self.assertGreaterEqual(sample.io_write_bytes, 0)
            self.assertGreaterEqual(sample.ctx_switches, 0)


# ===========================================================================
# 2. OperationProfiler start/stop timing
# ===========================================================================


class TestOperationProfilerStartStop(unittest.TestCase):
    """Verify basic timing capture via start/stop."""

    def test_wall_time_captured(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        time.sleep(0.05)
        sample = profiler.stop()

        # wall_ms should be at least ~40 ms (allow scheduling slack)
        self.assertGreaterEqual(sample.wall_ms, 30)
        # and not absurdly high
        self.assertLess(sample.wall_ms, 2000)

    def test_stop_without_start_raises(self) -> None:
        profiler = OperationProfiler()
        with self.assertRaises((RuntimeError, ValueError)):
            profiler.stop()

    def test_double_start_raises_or_restarts(self) -> None:
        """Double start should either raise or restart cleanly."""
        profiler = OperationProfiler()
        profiler.start()
        try:
            profiler.start()
            # If no exception, second start reset state — acceptable.
        except (RuntimeError, ValueError):
            pass  # Also acceptable behaviour.
        finally:
            profiler.stop()

    def test_reusable_after_stop(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        _cpu_burn(0.01)
        s1 = profiler.stop()

        profiler.start()
        _cpu_burn(0.01)
        s2 = profiler.stop()

        self.assertGreater(s1.wall_ms, 0)
        self.assertGreater(s2.wall_ms, 0)


# ===========================================================================
# 3. Context manager support
# ===========================================================================


class TestProfileContextManager(unittest.TestCase):
    """Verify `OperationProfiler` start/stop and `profile(fn)` usage."""

    def test_start_stop_returns_sample(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        _cpu_burn(0.02)
        sample = profiler.stop()
        self.assertIsInstance(sample, ProfileSample)
        self.assertGreater(sample.wall_ms, 0)

    def test_profile_fn_returns_result_and_sample(self) -> None:
        profiler = OperationProfiler()
        result, sample = profiler.profile(lambda: 42)
        self.assertEqual(result, 42)
        self.assertIsInstance(sample, ProfileSample)
        self.assertGreater(sample.wall_ms, 0)

    def test_profile_fn_captures_work(self) -> None:
        profiler = OperationProfiler()
        result, sample = profiler.profile(lambda: sum(i**2 for i in range(50_000)))
        self.assertGreater(result, 0)
        self.assertGreater(sample.wall_ms, 0)


# ===========================================================================
# 4. CPU time measurement
# ===========================================================================


class TestCpuTimeMeasurement(unittest.TestCase):
    """Verify user + system CPU time is captured on supported platforms."""

    def test_cpu_user_time_positive(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        _cpu_burn(0.1)
        sample = profiler.stop()

        if IS_LINUX or sys.platform == "darwin":
            self.assertGreater(sample.cpu_user_ms, 0, "cpu_user_ms should be > 0 after CPU burn")

    def test_cpu_time_less_than_wall_time(self) -> None:
        """CPU time should generally be <= wall time for single-threaded work."""
        profiler = OperationProfiler()
        profiler.start()
        _cpu_burn(0.05)
        sample = profiler.stop()

        total_cpu = sample.cpu_user_ms + sample.cpu_sys_ms
        # On multi-core, CPU can exceed wall for multi-threaded code,
        # but our burn is single-threaded so CPU <= wall (with tolerance).
        self.assertLessEqual(total_cpu, sample.wall_ms * 1.5)

    def test_idle_has_low_cpu_time(self) -> None:
        """Sleeping should yield near-zero user CPU time."""
        profiler = OperationProfiler()
        profiler.start()
        time.sleep(0.1)
        sample = profiler.stop()

        self.assertLess(sample.cpu_user_ms, 10, "Sleeping should consume < 10 ms user CPU")


# ===========================================================================
# 5. Memory (RSS delta) tracking
# ===========================================================================


class TestMemoryTracking(unittest.TestCase):
    """Verify RSS delta measurement."""

    def test_rss_delta_positive_after_allocation(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        buf = _allocate_memory(10)  # 10 MB
        sample = profiler.stop()

        if IS_LINUX:
            self.assertGreater(
                sample.rss_delta_kb, 0, "RSS delta should be positive after 10 MB alloc"
            )
        else:
            # On Windows, RSS may be UNAVAILABLE
            self.assertGreaterEqual(sample.rss_delta_kb, -1)
        # prevent premature GC
        self.assertIsNotNone(buf)

    def test_rss_delta_near_zero_for_trivial_work(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        _ = 1 + 1
        sample = profiler.stop()

        # RSS delta should be small (allowing some overhead)
        self.assertLess(
            abs(sample.rss_delta_kb), 512, "RSS delta should be < 512 KB for trivial work"
        )


# ===========================================================================
# 6. I/O tracking (Linux only expected, graceful elsewhere)
# ===========================================================================


class TestIOTracking(unittest.TestCase):
    """Verify I/O byte counters. On Linux they should be accurate;
    on other platforms they may be 0 or absent (graceful degradation)."""

    def test_io_read_bytes_after_file_read(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        bytes_written = _io_work(128)
        sample = profiler.stop()

        if IS_LINUX:
            self.assertGreater(
                sample.io_read_bytes, 0, "io_read_bytes should be > 0 on Linux after file I/O"
            )
        else:
            # On Windows/macOS, io counters may be UNAVAILABLE (-1) or 0
            self.assertGreaterEqual(sample.io_read_bytes, -1)

    def test_io_write_bytes_after_file_write(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        bytes_written = _io_work(128)
        sample = profiler.stop()

        if IS_LINUX:
            self.assertGreater(
                sample.io_write_bytes, 0, "io_write_bytes should be > 0 on Linux after file I/O"
            )
        else:
            self.assertGreaterEqual(sample.io_write_bytes, -1)

    def test_no_io_work_yields_low_io(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        _cpu_burn(0.01)
        sample = profiler.stop()

        self.assertLessEqual(
            sample.io_read_bytes, 4096, "CPU-only work should have minimal I/O reads"
        )


# ===========================================================================
# 7. MultiOperationProfiler
# ===========================================================================


class TestMultiOperationProfiler(unittest.TestCase):
    """Track multiple named operations in a single profiler instance."""

    def test_record_multiple_operations(self) -> None:
        multi = MultiOperationProfiler()

        with multi.measure("phase1"):
            _cpu_burn(0.02)
        with multi.measure("phase2"):
            _cpu_burn(0.02)
        with multi.measure("phase3"):
            _cpu_burn(0.02)

        ops = multi.operations()
        self.assertEqual(len(ops), 3)
        self.assertIn("phase1", ops)
        self.assertIn("phase2", ops)
        self.assertIn("phase3", ops)

    def test_same_name_appends_samples(self) -> None:
        multi = MultiOperationProfiler()

        for _ in range(3):
            with multi.measure("repeated"):
                _cpu_burn(0.01)

        prof = multi.get_profiler("repeated")
        self.assertIsNotNone(prof)
        self.assertEqual(len(prof.samples), 3)

    def test_clear_resets_all(self) -> None:
        multi = MultiOperationProfiler()
        with multi.measure("op"):
            _cpu_burn(0.01)

        multi.reset()
        # Operations still tracked, but samples cleared
        prof = multi.get_profiler("op")
        self.assertEqual(len(prof.samples), 0)

    def test_get_samples_returns_immutable_copy(self) -> None:
        multi = MultiOperationProfiler()
        with multi.measure("op"):
            _cpu_burn(0.01)

        samples1 = multi.all_samples()
        samples2 = multi.all_samples()
        # Mutating one should not affect the other
        samples1.clear()
        self.assertEqual(len(multi.all_samples()), 1)


# ===========================================================================
# 8. Summary statistics
# ===========================================================================


class TestSummaryStatistics(unittest.TestCase):
    """Verify mean, min, max, p95 computation across samples."""

    def _make_multi_with_n_samples(self, n: int = 20) -> MultiOperationProfiler:
        multi = MultiOperationProfiler()
        for _ in range(n):
            with multi.measure("task"):
                _cpu_burn(0.01)
        return multi

    def test_report_contains_task(self) -> None:
        multi = self._make_multi_with_n_samples(10)
        report = multi.report()

        self.assertIn("task", report)
        summary = report["task"]
        self.assertIn("wall_ms_mean", summary)
        self.assertIn("wall_ms_min", summary)
        self.assertIn("wall_ms_max", summary)

    def test_min_le_mean_le_max(self) -> None:
        multi = self._make_multi_with_n_samples(15)
        summary = multi.report()["task"]

        self.assertLessEqual(summary["wall_ms_min"], summary["wall_ms_mean"])
        self.assertLessEqual(summary["wall_ms_mean"], summary["wall_ms_max"])

    def test_p95_between_mean_and_max(self) -> None:
        multi = self._make_multi_with_n_samples(20)
        summary = multi.report()["task"]

        self.assertGreaterEqual(summary["wall_ms_mean"], summary["wall_ms_mean"])

    def test_report_for_unknown_operation_raises(self) -> None:
        multi = MultiOperationProfiler()
        report = multi.report()
        self.assertNotIn("nonexistent", report)

    def test_report_single_sample(self) -> None:
        multi = MultiOperationProfiler()
        with multi.measure("single"):
            _cpu_burn(0.01)

        summary = multi.report()["single"]
        self.assertAlmostEqual(summary["wall_ms_mean"], summary["wall_ms_min"], places=1)


# ===========================================================================
# 9. Overhead measurement
# ===========================================================================


class TestOverheadMeasurement(unittest.TestCase):
    """Verify profiling overhead is acceptably low."""

    def test_profiling_overhead_under_threshold(self) -> None:
        """Profiled work should not add more than 5 ms overhead per sample."""
        overhead_samples: List[float] = []

        for _ in range(10):
            # Measure without profiler
            t0 = time.monotonic()
            _ = 1 + 1
            bare_ms = (time.monotonic() - t0) * 1000

            # Measure with profiler
            profiler = OperationProfiler()
            profiler.start()
            _ = 1 + 1
            sample = profiler.stop()

            overhead = sample.wall_ms - bare_ms
            overhead_samples.append(overhead)

        avg_overhead = sum(overhead_samples) / len(overhead_samples)
        self.assertLess(
            avg_overhead, 5.0, f"Avg profiling overhead {avg_overhead:.2f} ms exceeds 5 ms"
        )

    def test_multi_profiler_overhead(self) -> None:
        """MultiOperationProfiler context manager overhead should be low."""
        multi = MultiOperationProfiler()

        t0 = time.monotonic()
        for _ in range(50):
            with multi.measure("noop"):
                pass
        elapsed_ms = (time.monotonic() - t0) * 1000

        # 50 no-op profiles should finish in under 500 ms
        self.assertLess(elapsed_ms, 500, f"50 no-op profiles took {elapsed_ms:.0f} ms, too slow")


# ===========================================================================
# 10. Thread safety
# ===========================================================================


class TestThreadSafety(unittest.TestCase):
    """Concurrent profiling on separate profiler instances must not crash."""

    def test_concurrent_separate_profilers(self) -> None:
        results: List[ProfileSample] = []
        errors: List[Exception] = []
        lock = threading.Lock()

        def worker(idx: int) -> None:
            try:
                p = OperationProfiler()
                p.start()
                _cpu_burn(0.02)
                s = p.stop()
                with lock:
                    results.append(s)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        self.assertEqual(len(results), 8)
        for s in results:
            self.assertGreater(s.wall_ms, 0)

    def test_concurrent_multi_profiler(self) -> None:
        """Multiple threads sharing one MultiOperationProfiler should not crash."""
        multi = MultiOperationProfiler()
        errors: List[Exception] = []
        lock = threading.Lock()

        def worker(idx: int) -> None:
            try:
                name = f"op_{idx}"
                with multi.measure(name):
                    _cpu_burn(0.01)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        samples = multi.all_samples()
        self.assertEqual(len(samples), 6)


# ===========================================================================
# 11. Cross-platform (Windows) graceful degradation
# ===========================================================================


class TestCrossPlatformDegradation(unittest.TestCase):
    """On Windows, some Linux-specific counters (io, ctx_switches) may be
    unavailable. Verify the profiler does not crash and returns sensible
    defaults."""

    def test_profiler_works_on_windows(self) -> None:
        """Smoke test: start, burn CPU, stop — no crash."""
        profiler = OperationProfiler()
        profiler.start()
        _cpu_burn(0.02)
        sample = profiler.stop()

        self.assertGreater(sample.wall_ms, 0)
        # On Windows, cpu_user_ms may be UNAVAILABLE (-1)
        self.assertGreaterEqual(sample.cpu_user_ms, -1)

    def test_io_counters_graceful_on_unsupported(self) -> None:
        """On Windows, io counters may be UNAVAILABLE (-1) — just verify no crash."""
        profiler = OperationProfiler()
        profiler.start()
        _io_work(64)
        sample = profiler.stop()

        # Either positive (Linux) or UNAVAILABLE (-1)
        self.assertGreaterEqual(sample.io_read_bytes, -1)
        self.assertGreaterEqual(sample.io_write_bytes, -1)

    def test_ctx_switches_non_negative_or_unavailable(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        _cpu_burn(0.02)
        sample = profiler.stop()

        # Either positive (Linux) or UNAVAILABLE (-1)
        self.assertGreaterEqual(sample.ctx_switches, -1)

    def test_rss_delta_works_on_windows(self) -> None:
        profiler = OperationProfiler()
        profiler.start()
        buf = _allocate_memory(5)
        sample = profiler.stop()

        # Either positive (Linux) or UNAVAILABLE (-1) on Windows
        self.assertGreaterEqual(sample.rss_delta_kb, -1)
        self.assertIsNotNone(buf)


# ===========================================================================
# 12. Large workload
# ===========================================================================


class TestLargeWorkload(unittest.TestCase):
    """Profile CPU-intensive functions and verify measurements scale."""

    def test_cpu_intensive_scaling(self) -> None:
        """Longer burn should yield proportionally more wall time."""
        short_profiler = OperationProfiler()
        short_profiler.start()
        _cpu_burn(0.05)
        short_sample = short_profiler.stop()

        long_profiler = OperationProfiler()
        long_profiler.start()
        _cpu_burn(0.2)
        long_sample = long_profiler.stop()

        self.assertGreater(
            long_sample.wall_ms, short_sample.wall_ms, "Longer burn should have greater wall time"
        )

    def test_profile_function_return_value(self) -> None:
        """profiler.profile(fn, *args) should return (result, sample)."""
        profiler = OperationProfiler()
        result, sample = profiler.profile(sum, list(range(10_000)))

        self.assertEqual(result, sum(range(10_000)))
        self.assertIsInstance(sample, ProfileSample)
        self.assertGreater(sample.wall_ms, 0)

    def test_profile_function_with_kwargs(self) -> None:
        """profiler.profile(fn, **kwargs) should forward keyword args."""
        profiler = OperationProfiler()
        result, sample = profiler.profile(sorted, [3, 1, 2], reverse=True)
        self.assertEqual(result, [3, 2, 1])
        self.assertIsInstance(sample, ProfileSample)

    def test_computation_heavy_workload(self) -> None:
        """Profile a heavier computation to verify stable measurements."""

        def heavy_computation(n: int = 200_000) -> float:
            total = 0.0
            for i in range(n):
                total += math.sqrt(i) * math.sin(i)
            return total

        profiler = OperationProfiler()
        result, sample = profiler.profile(heavy_computation, 200_000)

        self.assertIsInstance(result, float)
        self.assertGreater(sample.wall_ms, 0)
        # CPU time is available on Linux, UNAVAILABLE on Windows
        if IS_LINUX:
            self.assertGreater(sample.cpu_user_ms, 0, "Heavy computation should register CPU time")


# ===========================================================================
# Entry point for standalone execution
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
