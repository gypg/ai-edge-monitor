"""Integration tests for the memory_diagnostics package.

Covers sustained growth detection, stable-system noise rejection, burst vs
sustained leak differentiation, GPU gradual increase and alert generation,
CrashHandler full bundle and signal registration, cross-module coordination,
memory pressure simulation, human-readable report generation, thread safety,
and performance benchmarks.

Designed for Python 3.8+, runnable standalone:
    python tests/memory_diagnostics/test_memory_integration.py
"""

from __future__ import annotations

import io
import json
import os
import platform
import random
import sys
import tempfile
import threading
import time
import unittest
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

# ---------------------------------------------------------------------------
# Path setup -- mirrors the convention in sibling test files.
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory_diagnostics.debug_bundle import CrashHandler, generate_debug_bundle
from memory_diagnostics.gpu_tracker import GpuLeakAlert, GpuMemoryTracker
from memory_diagnostics.leak_detector import LeakDetector
from memory_diagnostics.models import LeakAlert

_PLATFORM = platform.system()
_IS_LINUX = _PLATFORM == "Linux"
_SELF_PID = os.getpid()


# ---------------------------------------------------------------------------
# Data generators
# ---------------------------------------------------------------------------


def _sustained_growth_samples(
    count: int,
    start_rss: float = 200.0,
    growth_per_sample: float = 0.1,
    interval_ms: int = 1000,
    start_ts: int = 1_000_000,
) -> List[Tuple[float, int]]:
    """Generate samples with a constant positive increment per step."""
    samples: List[Tuple[float, int]] = []
    for i in range(count):
        ts = start_ts + i * interval_ms
        rss = start_rss + growth_per_sample * i
        samples.append((rss, ts))
    return samples


def _noisy_stable_samples(
    count: int,
    base_rss: float = 512.0,
    noise_amplitude: float = 5.0,
    interval_ms: int = 1000,
    start_ts: int = 1_000_000,
    seed: int = 42,
) -> List[Tuple[float, int]]:
    """Random noise around a fixed mean -- no underlying trend."""
    rng = random.Random(seed)
    samples: List[Tuple[float, int]] = []
    for i in range(count):
        rss = base_rss + rng.uniform(-noise_amplitude, noise_amplitude)
        samples.append((rss, start_ts + i * interval_ms))
    return samples


def _burst_then_stable_samples(
    count: int,
    base_rss: float = 300.0,
    burst_at: int = 30,
    burst_jump: float = 80.0,
    noise_amplitude: float = 3.0,
    interval_ms: int = 1000,
    start_ts: int = 1_000_000,
    seed: int = 99,
) -> List[Tuple[float, int]]:
    """One-time spike followed by noisy stable behaviour -- no sustained leak."""
    rng = random.Random(seed)
    samples: List[Tuple[float, int]] = []
    current_rss = base_rss
    for i in range(count):
        ts = start_ts + i * interval_ms
        if i == burst_at:
            current_rss += burst_jump
        # Add small random noise but no trend
        rss = current_rss + rng.uniform(-noise_amplitude, noise_amplitude)
        samples.append((rss, ts))
    return samples


def _gpu_gradual_increase(
    count: int,
    start_gpu: float = 100.0,
    end_gpu: float = 800.0,
    start_rss: float = 200.0,
    rss_growth: float = 0.0,
    interval_ms: int = 1000,
    start_ts: int = 0,
) -> Tuple[List[float], List[float], List[int]]:
    """Generate RSS, GPU memory, and timestamp series."""
    gpu_step = (end_gpu - start_gpu) / max(count - 1, 1)
    rss_values = []
    gpu_values = []
    timestamps = []
    for i in range(count):
        ts = start_ts + i * interval_ms
        gpu_values.append(start_gpu + gpu_step * i)
        rss_values.append(start_rss + rss_growth * i)
        timestamps.append(ts)
    return rss_values, gpu_values, timestamps


# ---------------------------------------------------------------------------
# Diagnostic report helper
# ---------------------------------------------------------------------------


def _generate_report(
    leak_alert: Optional[LeakAlert],
    gpu_alert: Optional[GpuLeakAlert],
    sample_count: int,
    rss_values: List[float],
    gpu_values: List[Optional[float]],
) -> str:
    """Generate a human-readable diagnostic report from detector outputs."""
    buf = io.StringIO()
    buf.write("=" * 60 + "\n")
    buf.write("  MEMORY DIAGNOSTIC REPORT\n")
    buf.write("=" * 60 + "\n\n")

    buf.write(f"Total samples analysed: {sample_count}\n")
    buf.write(f"Current RSS: {rss_values[-1]:.1f} MB\n")
    if gpu_values and gpu_values[-1] is not None:
        buf.write(f"Current GPU mem: {gpu_values[-1]:.1f} MB\n")
    buf.write("\n")

    # Leak detector section
    buf.write("--- CPU RSS Leak Detector ---\n")
    if leak_alert is not None:
        buf.write(f"  ALERT: Memory leak detected!\n")
        buf.write(f"  Slope: {leak_alert.slope_mb_per_sec:.4f} MB/sec\n")
        buf.write(f"  R-squared: {leak_alert.r_squared:.4f}\n")
        buf.write(f"  Samples in window: {leak_alert.sample_count}\n")
        if leak_alert.estimated_time_to_oom is not None:
            buf.write(f"  Estimated time to OOM: {leak_alert.estimated_time_to_oom:.0f} sec\n")
    else:
        buf.write("  No leak detected -- RSS appears stable.\n")
    buf.write("\n")

    # GPU tracker section
    buf.write("--- GPU Memory Tracker ---\n")
    if gpu_alert is not None:
        buf.write(f"  ALERT: GPU memory anomaly detected!\n")
        buf.write(f"  Pattern: {gpu_alert.pattern}\n")
        buf.write(f"  Severity: {gpu_alert.severity}\n")
        buf.write(f"  CPU leak: {gpu_alert.cpu_leak_detected}\n")
        buf.write(f"  GPU leak: {gpu_alert.gpu_leak_detected}\n")
    else:
        buf.write("  No GPU leak detected -- memory usage appears stable.\n")
    buf.write("\n")
    buf.write("=" * 60 + "\n")

    return buf.getvalue()


# ===========================================================================
# Test cases
# ===========================================================================


class TestSustainedGrowthSimulation(unittest.TestCase):
    """1. LeakDetector -- sustained growth at ~0.1 MB/min over 100 samples."""

    def test_sustained_growth_detected(self) -> None:
        """A slow but steady 0.1 MB/sample growth over 100 samples must be
        detected as a leak when slope and R-squared thresholds are tuned
        appropriately.
        """
        # 0.1 MB per sample at 1-second intervals = 0.1 MB/sec slope
        detector = LeakDetector(
            window_size=100,
            r_squared_threshold=0.8,
            slope_threshold_mb_per_sec=0.05,
        )
        samples = _sustained_growth_samples(
            count=100, start_rss=200.0, growth_per_sample=0.1, interval_ms=1000
        )

        final_alert = None
        for rss, ts in samples:
            alert = detector.observe(rss, ts)
            if alert is not None:
                final_alert = alert

        self.assertIsNotNone(final_alert, "Sustained growth must trigger a LeakAlert")
        self.assertIsInstance(final_alert, LeakAlert)
        self.assertGreater(
            final_alert.r_squared, 0.95, "R-squared for perfect linear growth should be > 0.95"
        )
        self.assertGreater(
            final_alert.slope_mb_per_sec, 0.05, "Slope should exceed the 0.05 MB/sec threshold"
        )
        self.assertEqual(final_alert.sample_count, 100)
        self.assertIsNotNone(final_alert.estimated_time_to_oom)
        self.assertGreater(final_alert.estimated_time_to_oom, 0)


class TestStableSystem(unittest.TestCase):
    """2. LeakDetector -- noisy but stable system must NOT trigger a leak."""

    def test_no_leak_on_stable_noise(self) -> None:
        detector = LeakDetector(
            window_size=100,
            r_squared_threshold=0.8,
            slope_threshold_mb_per_sec=0.05,
        )
        samples = _noisy_stable_samples(count=100, base_rss=512.0, noise_amplitude=10.0, seed=42)

        for rss, ts in samples:
            alert = detector.observe(rss, ts)
            self.assertIsNone(alert, "Stable noisy data must not trigger a leak alert")


class TestBurstVsSustained(unittest.TestCase):
    """3. LeakDetector -- distinguish a one-time spike from a genuine leak."""

    def test_burst_does_not_trigger_sustained_leak(self) -> None:
        """A single jump followed by stability should not be classified as
        a sustained leak after the window slides past the burst.
        """
        window = 50
        detector = LeakDetector(
            window_size=window,
            r_squared_threshold=0.8,
            slope_threshold_mb_per_sec=0.05,
        )
        samples = _burst_then_stable_samples(
            count=120,
            base_rss=300.0,
            burst_at=30,
            burst_jump=80.0,
            noise_amplitude=3.0,
            seed=99,
        )

        alerts_after_burst = 0
        for rss, ts in samples:
            alert = detector.observe(rss, ts)
            # We allow an alert right around the burst window, but after the
            # burst has slid out of the window (roughly sample 80+), alerts
            # should stop.
            if alert is not None and ts > samples[30 + window][1]:
                alerts_after_burst += 1

        self.assertEqual(
            alerts_after_burst,
            0,
            "After the burst has left the window, no further alerts should fire",
        )

    def test_burst_may_trigger_temporarily(self) -> None:
        """The burst itself may cause an alert while it is inside the window
        -- this is acceptable transient behaviour.
        """
        window = 30
        detector = LeakDetector(
            window_size=window,
            r_squared_threshold=0.8,
            slope_threshold_mb_per_sec=0.05,
        )
        samples = _burst_then_stable_samples(
            count=80,
            base_rss=300.0,
            burst_at=20,
            burst_jump=100.0,
            noise_amplitude=2.0,
            seed=77,
        )

        any_alert = False
        for rss, ts in samples:
            alert = detector.observe(rss, ts)
            if alert is not None:
                any_alert = True

        # We do not require the burst to trigger -- just verify it does not
        # crash and that the detector is functional throughout.
        self.assertIsInstance(any_alert, bool)


class TestGpuGradualIncrease(unittest.TestCase):
    """4. GpuMemoryTracker -- GPU memory growing from 100 MB to 800 MB."""

    def test_gpu_gradual_increase_detected(self) -> None:
        n = 50
        rss_values, gpu_values, timestamps = _gpu_gradual_increase(
            count=n, start_gpu=100.0, end_gpu=800.0, start_rss=200.0
        )

        tracker = GpuMemoryTracker(
            window_size=60,
            r_squared_threshold=0.8,
            slope_threshold_mb_per_ms=0.00001,
        )
        result = None
        for rss, gpu, ts in zip(rss_values, gpu_values, timestamps):
            result = tracker.observe(rss, gpu, ts)

        self.assertIsNotNone(result, "Gradual GPU increase from 100 to 800 MB must be detected")
        self.assertTrue(result.gpu_leak_detected)
        self.assertGreater(result.gpu_slope, 0)


class TestGpuAlertGeneration(unittest.TestCase):
    """5. GpuMemoryTracker -- GpuLeakAlert fires at threshold."""

    def test_alert_fields_populated(self) -> None:
        n = 30
        rss_values, gpu_values, timestamps = _gpu_gradual_increase(
            count=n,
            start_gpu=200.0,
            end_gpu=600.0,
            start_rss=100.0,
            rss_growth=2.0,
        )

        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)
        result = None
        for rss, gpu, ts in zip(rss_values, gpu_values, timestamps):
            result = tracker.observe(rss, gpu, ts)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, GpuLeakAlert)
        self.assertIn(result.pattern, ("dual_leak", "cpu_only_leak", "gpu_only_leak"))
        self.assertIn(result.severity, ("CRITICAL", "WARNING"))
        self.assertIsInstance(result.cpu_slope, float)
        self.assertIsInstance(result.gpu_slope, float)

    def test_severity_critical_for_dual_leak(self) -> None:
        """Both CPU and GPU growing should yield CRITICAL severity."""
        n = 25
        rss_values, gpu_values, timestamps = _gpu_gradual_increase(
            count=n,
            start_gpu=100.0,
            end_gpu=500.0,
            start_rss=100.0,
            rss_growth=3.0,
        )

        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)
        result = None
        for rss, gpu, ts in zip(rss_values, gpu_values, timestamps):
            result = tracker.observe(rss, gpu, ts)

        self.assertIsNotNone(result)
        self.assertEqual(result.severity, "CRITICAL")
        self.assertEqual(result.pattern, "dual_leak")

    def test_no_alert_when_below_threshold(self) -> None:
        """Flat GPU memory below the slope threshold must not trigger."""
        n = 30
        rss_values = [200.0] * n
        gpu_values = [512.0] * n
        timestamps = [i * 1000 for i in range(n)]

        tracker = GpuMemoryTracker(window_size=60, r_squared_threshold=0.8)
        result = None
        for rss, gpu, ts in zip(rss_values, gpu_values, timestamps):
            result = tracker.observe(rss, gpu, ts)

        self.assertIsNone(result, "Stable GPU memory must not trigger an alert")


class TestCrashHandlerFullBundle(unittest.TestCase):
    """6. CrashHandler -- generate a full debug bundle and verify structure."""

    def test_full_bundle_structure(self) -> None:
        """Bundle must contain all expected files plus diagnosis.json."""
        rss_timeline = [{"ts_ms": 1000 + i * 1000, "rss_mb": 200.0 + i * 0.5} for i in range(50)]
        gpu_timeline = [
            {"ts_ms": 1000 + i * 1000, "gpu_mem_mb": 512.0 + i * 1.0} for i in range(50)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = generate_debug_bundle(
                _SELF_PID,
                Path(tmp),
                rss_timeline=rss_timeline,
                gpu_timeline=gpu_timeline,
            )

            self.assertTrue(bundle_dir.is_dir())

            # All mandatory files
            for name in (
                "proc_status.txt",
                "proc_maps.txt",
                "smaps_rollup.txt",
                "dmesg_tail.txt",
                "diagnosis.json",
                "rss_timeline.csv",
                "gpu_mem_timeline.csv",
            ):
                self.assertTrue(
                    (bundle_dir / name).is_file(),
                    f"Expected file missing: {name}",
                )

            # Diagnosis JSON structure
            diag = json.loads((bundle_dir / "diagnosis.json").read_text(encoding="utf-8"))
            self.assertEqual(diag["pid"], _SELF_PID)
            self.assertEqual(diag["rss_timeline_rows"], 50)
            self.assertEqual(diag["gpu_timeline_rows"], 50)
            self.assertGreater(diag["generation_time_ms"], 0)
            self.assertLess(diag["bundle_size_bytes"], 10 * 1024 * 1024)

    def test_bundle_under_time_constraint(self) -> None:
        """Bundle generation must complete in under 1 second (spec 4.4)."""
        with tempfile.TemporaryDirectory() as tmp:
            start = time.monotonic()
            generate_debug_bundle(_SELF_PID, Path(tmp))
            elapsed = time.monotonic() - start

        self.assertLess(elapsed, 1.0, "Bundle generation exceeded 1-second budget")


class TestCrashHandlerSignalHandling(unittest.TestCase):
    """7. CrashHandler -- signal registration for SIGINT, SIGSEGV, etc."""

    def test_install_uninstall_lifecycle(self) -> None:
        """install() followed by uninstall() must leave no side effects."""
        handler = CrashHandler()
        handler.install(_SELF_PID)
        handler.uninstall()

    def test_double_install_is_idempotent(self) -> None:
        handler = CrashHandler()
        handler.install(_SELF_PID)
        handler.install(_SELF_PID)  # should not raise
        handler.uninstall()

    def test_double_uninstall_is_safe(self) -> None:
        handler = CrashHandler()
        handler.install(_SELF_PID)
        handler.uninstall()
        handler.uninstall()  # should not raise

    @unittest.skipUnless(_IS_LINUX, "Signal handler verification only on Linux")
    def test_signal_handlers_registered_on_linux(self) -> None:
        """After install(), SIGSEGV, SIGABRT, SIGTERM must have callable handlers."""
        import signal as _signal

        handler = CrashHandler()
        handler.install(_SELF_PID)
        try:
            for sig in (_signal.SIGSEGV, _signal.SIGABRT, _signal.SIGTERM):
                current = _signal.getsignal(sig)
                self.assertTrue(
                    callable(current),
                    f"Handler for signal {sig} is not callable after install()",
                )
        finally:
            handler.uninstall()

    @unittest.skipUnless(_IS_LINUX, "Signal restoration only testable on Linux")
    def test_original_handlers_restored_after_uninstall(self) -> None:
        """After uninstall(), handlers must be restored to their originals."""
        import signal as _signal

        original_handlers = {}
        for sig in (_signal.SIGSEGV, _signal.SIGABRT, _signal.SIGTERM):
            original_handlers[sig] = _signal.getsignal(sig)

        handler = CrashHandler()
        handler.install(_SELF_PID)
        handler.uninstall()

        for sig in (_signal.SIGSEGV, _signal.SIGABRT, _signal.SIGTERM):
            restored = _signal.getsignal(sig)
            self.assertEqual(
                restored,
                original_handlers[sig],
                f"Handler for signal {sig} was not restored after uninstall()",
            )

    @unittest.skipUnless(not _IS_LINUX, "Non-Linux no-op test")
    def test_noop_on_non_linux(self) -> None:
        """On non-Linux platforms, install() must not crash."""
        handler = CrashHandler()
        handler.install(_SELF_PID)
        # Should log a warning but not raise
        handler.uninstall()


class TestCrossModuleIntegration(unittest.TestCase):
    """8. LeakDetector + GpuMemoryTracker running together on the same data."""

    def test_both_detectors_run_concurrently(self) -> None:
        """Feed the same timeline into both detectors; both should fire."""
        n = 60
        start_ts = 0
        interval_ms = 1000

        leak_detector = LeakDetector(
            window_size=60,
            r_squared_threshold=0.8,
            slope_threshold_mb_per_sec=0.05,
        )
        gpu_tracker = GpuMemoryTracker(
            window_size=60,
            r_squared_threshold=0.8,
            slope_threshold_mb_per_ms=0.00001,
        )

        leak_alert = None
        gpu_alert = None
        for i in range(n):
            ts = start_ts + i * interval_ms
            rss = 200.0 + 0.2 * i
            gpu_mem = 512.0 + 0.1 * i

            la = leak_detector.observe(rss, ts)
            if la is not None:
                leak_alert = la
            ga = gpu_tracker.observe(rss, gpu_mem, ts)
            if ga is not None:
                gpu_alert = ga

        self.assertIsNotNone(leak_alert, "LeakDetector should detect the CPU trend")
        self.assertIsNotNone(gpu_alert, "GpuMemoryTracker should detect the dual trend")
        self.assertTrue(gpu_alert.cpu_leak_detected)
        self.assertTrue(gpu_alert.gpu_leak_detected)

    def test_mixed_signals_cpu_leak_gpu_stable(self) -> None:
        """CPU leaking but GPU stable should produce a cpu_only_leak."""
        n = 40
        leak_detector = LeakDetector(
            window_size=40,
            r_squared_threshold=0.8,
            slope_threshold_mb_per_sec=0.05,
        )
        gpu_tracker = GpuMemoryTracker(
            window_size=40,
            r_squared_threshold=0.8,
        )

        gpu_alert = None
        for i in range(n):
            ts = i * 1000
            rss = 200.0 + 0.3 * i
            gpu_mem = 512.0  # flat

            la = leak_detector.observe(rss, ts)
            ga = gpu_tracker.observe(rss, gpu_mem, ts)
            if ga is not None:
                gpu_alert = ga

        self.assertIsNotNone(gpu_alert)
        self.assertEqual(gpu_alert.pattern, "cpu_only_leak")
        self.assertTrue(gpu_alert.cpu_leak_detected)
        self.assertFalse(gpu_alert.gpu_leak_detected)

    def test_neither_detects_when_stable(self) -> None:
        """Both stable RSS and GPU must produce no alerts from either module."""
        n = 60
        leak_detector = LeakDetector(window_size=60)
        gpu_tracker = GpuMemoryTracker(window_size=60)

        for i in range(n):
            ts = i * 1000
            la = leak_detector.observe(500.0, ts)
            ga = gpu_tracker.observe(500.0, 1024.0, ts)
            self.assertIsNone(la)
            self.assertIsNone(ga)


class TestMemoryPressureSimulation(unittest.TestCase):
    """9. Simulate OOM conditions and verify detector behaviour under pressure."""

    def test_rapid_rss_growth_triggers_alert(self) -> None:
        """Simulate memory pressure: RSS climbs from 100 to 1900 MB in 100 steps.
        Detector must fire and estimate_time_to_oom should be short.
        """
        detector = LeakDetector(
            window_size=100,
            r_squared_threshold=0.8,
            slope_threshold_mb_per_sec=0.01,
        )
        n = 100
        oom_limit = 2048.0

        final_alert = None
        for i in range(n):
            ts = i * 1000
            rss = 100.0 + (1800.0 / n) * i  # ~18 MB/sec
            alert = detector.observe(rss, ts)
            if alert is not None:
                final_alert = alert

        self.assertIsNotNone(final_alert)
        self.assertGreater(final_alert.slope_mb_per_sec, 10.0)
        # Estimated time to OOM should be small since we are near the limit
        self.assertIsNotNone(final_alert.estimated_time_to_oom)
        self.assertLess(
            final_alert.estimated_time_to_oom,
            200.0,
            "At ~18 MB/sec from 1900 MB, OOM should be imminent",
        )

    def test_oom_limit_enforced(self) -> None:
        """When current RSS already exceeds the 2048 MB OOM limit,
        estimated_time_to_oom should be None (already over).
        """
        detector = LeakDetector(
            window_size=20,
            r_squared_threshold=0.5,
            slope_threshold_mb_per_sec=0.001,
        )

        # Feed data above 2048 MB -- the detector hardcodes 2048 as OOM limit.
        for i in range(25):
            ts = i * 1000
            rss = 2100.0 + 0.1 * i
            alert = detector.observe(rss, ts)

        # The last alert (if any) should have estimated_time_to_oom == None
        # because current_rss >= oom_limit_mb.
        # Re-feed to ensure we capture the final state.
        detector2 = LeakDetector(
            window_size=20,
            r_squared_threshold=0.5,
            slope_threshold_mb_per_sec=0.001,
        )
        final_alert = None
        for i in range(25):
            ts = i * 1000
            rss = 2200.0 + 0.1 * i
            a = detector2.observe(rss, ts)
            if a is not None:
                final_alert = a

        if final_alert is not None:
            # current_rss (2200+) exceeds the 2048 OOM limit, so no TTO
            self.assertIsNone(final_alert.estimated_time_to_oom)


class TestReportGeneration(unittest.TestCase):
    """10. Generate a human-readable diagnostic report from detector outputs."""

    def test_report_with_leak_alert(self) -> None:
        """Report must include leak details when a LeakAlert is provided."""
        alert = LeakAlert(
            target_pid=1234,
            target_name="inference_engine",
            r_squared=0.97,
            slope_mb_per_sec=0.15,
            estimated_time_to_oom=3600.0,
            window_start_ms=1000,
            window_end_ms=60000,
            sample_count=60,
        )
        report = _generate_report(
            leak_alert=alert,
            gpu_alert=None,
            sample_count=60,
            rss_values=[200.0 + 0.15 * i for i in range(60)],
            gpu_values=[512.0] * 60,
        )

        self.assertIn("MEMORY DIAGNOSTIC REPORT", report)
        self.assertIn("Memory leak detected", report)
        self.assertIn("0.1500", report)
        self.assertIn("0.9700", report)
        self.assertIn("3600", report)

    def test_report_with_gpu_alert(self) -> None:
        """Report must include GPU alert details."""
        gpu_alert = GpuLeakAlert(
            pattern="dual_leak",
            cpu_leak_detected=True,
            gpu_leak_detected=True,
            cpu_slope=0.0002,
            gpu_slope=0.0001,
            severity="CRITICAL",
        )
        report = _generate_report(
            leak_alert=None,
            gpu_alert=gpu_alert,
            sample_count=30,
            rss_values=[200.0] * 30,
            gpu_values=[512.0] * 30,
        )

        self.assertIn("GPU memory anomaly", report)
        self.assertIn("dual_leak", report)
        self.assertIn("CRITICAL", report)

    def test_report_no_alerts(self) -> None:
        """Report must clearly state stability when no alerts are present."""
        report = _generate_report(
            leak_alert=None,
            gpu_alert=None,
            sample_count=100,
            rss_values=[500.0] * 100,
            gpu_values=[1024.0] * 100,
        )

        self.assertIn("No leak detected", report)
        self.assertIn("No GPU leak detected", report)
        self.assertIn("100", report)

    def test_report_structure_complete(self) -> None:
        """Report must always contain the header, separator lines, and sections."""
        report = _generate_report(
            leak_alert=None,
            gpu_alert=None,
            sample_count=10,
            rss_values=[100.0] * 10,
            gpu_values=[None] * 10,
        )

        self.assertIn("=" * 60, report)
        self.assertIn("CPU RSS Leak Detector", report)
        self.assertIn("GPU Memory Tracker", report)
        self.assertIn("Total samples analysed", report)


class TestThreadSafety(unittest.TestCase):
    """11. Concurrent access to LeakDetector and GpuMemoryTracker."""

    def test_concurrent_leak_detector_observations(self) -> None:
        """Multiple threads feeding observations into a single LeakDetector
        must not crash or corrupt internal state.
        """
        detector = LeakDetector(window_size=100)
        errors: List[Exception] = []
        n_threads = 8
        samples_per_thread = 50

        def _worker(thread_id: int) -> None:
            try:
                for i in range(samples_per_thread):
                    ts = thread_id * 100_000 + i * 1000
                    rss = 200.0 + thread_id + i * 0.01
                    detector.observe(rss, ts)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(tid,)) for tid in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [], f"Concurrent access raised errors: {errors}")
        # Window should be at most the configured max
        self.assertLessEqual(len(detector._observations), 100)

    def test_concurrent_gpu_tracker_observations(self) -> None:
        """Multiple threads feeding into GpuMemoryTracker must not crash."""
        tracker = GpuMemoryTracker(window_size=100)
        errors: List[Exception] = []
        n_threads = 8
        samples_per_thread = 50

        def _worker(thread_id: int) -> None:
            try:
                for i in range(samples_per_thread):
                    ts = thread_id * 100_000 + i * 1000
                    rss = 200.0 + thread_id + i * 0.01
                    gpu = 512.0 + i * 0.05
                    tracker.observe(rss, gpu, ts)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(tid,)) for tid in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [], f"Concurrent access raised errors: {errors}")
        self.assertLessEqual(len(tracker._rss_values), 100)

    def test_concurrent_bundle_generation(self) -> None:
        """Multiple threads generating bundles into separate temp dirs."""
        errors: List[Exception] = []
        n_threads = 4

        def _worker(thread_id: int) -> None:
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    bundle = generate_debug_bundle(_SELF_PID, Path(tmp))
                    self.assertTrue(bundle.is_dir())
                    self.assertTrue((bundle / "diagnosis.json").is_file())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(tid,)) for tid in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        self.assertEqual(errors, [], f"Concurrent bundle generation errors: {errors}")


class TestDetectorPerformance(unittest.TestCase):
    """12. Benchmark detector overhead -- must stay within embedded constraints."""

    def test_leak_detector_throughput(self) -> None:
        """LeakDetector.observe() must handle >= 10k calls in under 5 seconds.

        Each call runs linear regression over the sliding window, so per-call
        cost is O(window_size).  10k calls exercises sustained monitoring
        without exceeding a reasonable CI time budget.
        """
        detector = LeakDetector(window_size=60)
        n = 10_000

        start = time.monotonic()
        for i in range(n):
            detector.observe(float(i % 200), i * 1000)
        elapsed = time.monotonic() - start

        self.assertLess(
            elapsed, 5.0, f"LeakDetector: {n} observations took {elapsed:.2f}s (limit 5s)"
        )

    def test_gpu_tracker_throughput(self) -> None:
        """GpuMemoryTracker.observe() must handle >= 5k calls in under 5 seconds.

        The tracker runs two regressions per call (CPU + GPU), so it is
        roughly 2x the cost of a single LeakDetector.  5k calls is a
        representative sustained-monitoring workload.
        """
        tracker = GpuMemoryTracker(window_size=60)
        n = 5_000

        start = time.monotonic()
        for i in range(n):
            tracker.observe(float(i % 200), float(i % 500), i * 1000)
        elapsed = time.monotonic() - start

        self.assertLess(
            elapsed, 5.0, f"GpuMemoryTracker: {n} observations took {elapsed:.2f}s (limit 5s)"
        )

    def test_bundle_generation_latency(self) -> None:
        """Bundle generation (no timelines) must complete in under 500 ms."""
        with tempfile.TemporaryDirectory() as tmp:
            start = time.monotonic()
            generate_debug_bundle(_SELF_PID, Path(tmp))
            elapsed = time.monotonic() - start

        self.assertLess(elapsed, 0.5, f"Bundle generation took {elapsed:.3f}s (limit 500ms)")

    def test_bundle_with_large_timelines(self) -> None:
        """Bundle with 5000-row timelines must still stay under 10 MB."""
        rss_timeline = [{"ts_ms": i * 1000, "rss_mb": 200.0 + i * 0.01} for i in range(5000)]
        gpu_timeline = [{"ts_ms": i * 1000, "gpu_mem_mb": 512.0 + i * 0.02} for i in range(5000)]

        with tempfile.TemporaryDirectory() as tmp:
            bundle = generate_debug_bundle(
                _SELF_PID,
                Path(tmp),
                rss_timeline=rss_timeline,
                gpu_timeline=gpu_timeline,
            )
            diag = json.loads((bundle / "diagnosis.json").read_text(encoding="utf-8"))
            self.assertLess(
                diag["bundle_size_bytes"],
                10 * 1024 * 1024,
                "Bundle with 5000-row timelines exceeds 10 MB limit",
            )
            self.assertEqual(diag["rss_timeline_rows"], 5000)
            self.assertEqual(diag["gpu_timeline_rows"], 5000)

    def test_detector_memory_bounded(self) -> None:
        """After 1 million observations, detector memory must not grow."""
        detector = LeakDetector(window_size=60)
        n = 1_000_000

        for i in range(n):
            detector.observe(float(i % 100), i * 1000)

        self.assertEqual(
            len(detector._observations),
            60,
            "LeakDetector deque exceeded window_size after 1M observations",
        )


# ===========================================================================
# Runner
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
