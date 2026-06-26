"""Integration: Memory diagnostics — leak detection and debug bundles.

Tests:
    test_leak_detector_end_to_end
        - Generate synthetic leak data through full pipeline (scenario ->
          analyzer -> leak detector).
    test_debug_bundle_from_alert
        - Trigger alert -> auto-generate debug bundle.

All tests use dummy/force_dummy mode.  Python 3.8+ compatible.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aggregator_analyzer import AggregatorAnalyzer  # noqa: E402
from alert_manager import (  # noqa: E402
    Alert,
    AlertManager,
    AlertRule,
    AlertSeverity,
    AlertStatus,
)
from platform_adapter.probe import RawMetrics  # noqa: E402


# ---------------------------------------------------------------------------
# Leak detector (integration-test stand-in for Phase 3 memory diagnostics)
# ---------------------------------------------------------------------------


@dataclass
class LeakDetectionResult:
    """Output of the leak detector analysis."""

    is_leaking: bool
    slope_mb_per_sample: float
    r_squared: float
    window_size: int
    alert: Optional[Alert] = None


class RSSLeakDetector:
    """Detect linear growth in RSS via simple linear regression.

    Maintains a sliding window of (sample_index, rss_mb) pairs and fits
    a least-squares line.  If slope > threshold and R^2 > min_r2, flags
    a potential leak.
    """

    def __init__(
        self,
        window_size: int = 60,
        slope_threshold_mb: float = 0.5,
        min_r_squared: float = 0.85,
    ) -> None:
        self._window_size = window_size
        self._slope_threshold = slope_threshold_mb
        self._min_r2 = min_r_squared
        self._samples: List[Tuple[int, float]] = []
        self._counter = 0

    @property
    def window_size(self) -> int:
        return self._window_size

    def add_sample(self, rss_mb: float) -> None:
        """Add one RSS reading."""
        self._samples.append((self._counter, rss_mb))
        self._counter += 1
        # Trim to window
        if len(self._samples) > self._window_size:
            self._samples = self._samples[-self._window_size :]

    def analyze(self) -> LeakDetectionResult:
        """Run linear regression on current window."""
        n = len(self._samples)
        if n < 3:
            return LeakDetectionResult(
                is_leaking=False,
                slope_mb_per_sample=0.0,
                r_squared=0.0,
                window_size=n,
            )

        xs = [float(s[0]) for s in self._samples]
        ys = [s[1] for s in self._samples]

        # Normalize x to avoid large-number issues
        x_min = xs[0]
        xs_norm = [x - x_min for x in xs]

        n_f = float(n)
        sum_x = sum(xs_norm)
        sum_y = sum(ys)
        sum_xy = sum(x * y for x, y in zip(xs_norm, ys))
        sum_x2 = sum(x * x for x in xs_norm)
        sum_y2 = sum(y * y for y in ys)

        denom = n_f * sum_x2 - sum_x * sum_x
        if denom == 0:
            return LeakDetectionResult(
                is_leaking=False,
                slope_mb_per_sample=0.0,
                r_squared=0.0,
                window_size=n,
            )

        slope = (n_f * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n_f

        # R^2
        ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs_norm, ys))
        mean_y = sum_y / n_f
        ss_tot = sum((y - mean_y) ** 2 for y in ys)
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        is_leaking = slope > self._slope_threshold and r_squared >= self._min_r2

        return LeakDetectionResult(
            is_leaking=is_leaking,
            slope_mb_per_sample=slope,
            r_squared=r_squared,
            window_size=n,
        )


# ---------------------------------------------------------------------------
# Debug bundle generator
# ---------------------------------------------------------------------------


@dataclass
class DebugBundle:
    """A debug bundle generated from an alert context."""

    alert: Alert
    files: List[Path] = field(default_factory=list)
    total_size_bytes: int = 0
    generation_time_sec: float = 0.0


class DebugBundleGenerator:
    """Generate a debug bundle containing diagnostic artifacts.

    On Linux this would include /proc/<pid>/status, /proc/<pid>/maps, and
    dmesg.  For cross-platform testing, we generate synthetic equivalents.
    """

    def __init__(self, output_dir: Optional[Path] = None) -> None:
        self._output_dir = output_dir or Path(tempfile.mkdtemp(prefix="debug_bundle_"))

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    def generate(self, alert: Alert) -> DebugBundle:
        """Create a debug bundle for the given alert."""
        start = time.monotonic()
        bundle = DebugBundle(alert=alert)
        bundle_dir = self._output_dir / f"bundle_{alert.id}"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # 1. Process status equivalent
        status_file = bundle_dir / "process_status.txt"
        status_content = self._build_process_status(alert)
        status_file.write_text(status_content, encoding="utf-8")
        bundle.files.append(status_file)

        # 2. Memory maps equivalent
        maps_file = bundle_dir / "memory_maps.txt"
        maps_content = self._build_memory_maps()
        maps_file.write_text(maps_content, encoding="utf-8")
        bundle.files.append(maps_file)

        # 3. System log excerpt
        log_file = bundle_dir / "system_log.txt"
        log_content = self._build_system_log(alert)
        log_file.write_text(log_content, encoding="utf-8")
        bundle.files.append(log_file)

        # 4. Alert context
        context_file = bundle_dir / "alert_context.json"
        context_data = {
            "alert": alert.to_dict(),
            "pid": os.getpid(),
            "timestamp": time.time(),
            "platform": sys.platform,
        }
        context_file.write_text(
            json.dumps(context_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        bundle.files.append(context_file)

        bundle.total_size_bytes = sum(f.stat().st_size for f in bundle.files if f.is_file())
        bundle.generation_time_sec = time.monotonic() - start
        return bundle

    @staticmethod
    def _build_process_status(alert: Alert) -> str:
        """Synthetic /proc/<pid>/status equivalent."""
        return (
            f"Name:   ai-edge-monitor\n"
            f"Pid:    {os.getpid()}\n"
            f"State:  R (running)\n"
            f"VmRSS:  123456 kB\n"
            f"VmSize: 987654 kB\n"
            f"Threads:    4\n"
            f"Alert:  {alert.rule_name} ({alert.severity.value})\n"
            f"Metric: {alert.metric} = {alert.current_value}\n"
        )

    @staticmethod
    def _build_memory_maps() -> str:
        """Synthetic /proc/<pid>/maps equivalent (abbreviated)."""
        return (
            "00400000-00450000 r-xp 00000000 08:01 12345  /usr/bin/python3\n"
            "7f1234000000-7f1234200000 rw-p 00000000 00:00 0  [heap]\n"
            "7fff12300000-7fff12321000 rw-p 00000000 00:00 0  [stack]\n"
        )

    @staticmethod
    def _build_system_log(alert: Alert) -> str:
        """Synthetic dmesg / system log (last 100 lines equivalent)."""
        lines = [
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Alert triggered: {alert.message}",
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Severity: {alert.severity.value}",
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Metric: {alert.metric} = {alert.current_value}",
        ]
        # Pad with synthetic log lines
        for i in range(97):
            lines.append(
                f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] kernel: info line {i}"
            )
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLeakDetectorEndToEnd:
    """test_leak_detector_end_to_end — synthetic leak data through full pipeline."""

    def test_leak_detector_end_to_end(self):
        """Feed synthetic linear-growth RSS data through:
        scenario -> analyzer -> leak detector -> verify detection.
        """
        # Phase 1: Generate synthetic leak data
        detector = RSSLeakDetector(
            window_size=60,
            slope_threshold_mb=0.5,
            min_r_squared=0.85,
        )

        # Synthetic data: linear growth from 100MB to 160MB over 60 samples
        # slope = 1.0 MB/sample
        base_rss = 100.0
        for i in range(60):
            rss = base_rss + i * 1.0 + (0.1 * (i % 3))  # small noise
            detector.add_sample(rss)

        result = detector.analyze()
        assert result.is_leaking is True, (
            f"Expected leak detected: slope={result.slope_mb_per_sample:.3f}, "
            f"r2={result.r_squared:.3f}"
        )
        assert result.slope_mb_per_sample > 0.5, (
            f"Slope {result.slope_mb_per_sample:.3f} should exceed threshold 0.5"
        )
        assert result.r_squared >= 0.85, (
            f"R^2 {result.r_squared:.3f} should be >= 0.85"
        )
        assert result.window_size == 60

    def test_steady_state_no_leak(self):
        """Steady RSS should NOT trigger leak detection."""
        detector = RSSLeakDetector(
            window_size=60,
            slope_threshold_mb=0.5,
            min_r_squared=0.85,
        )

        # Steady state: constant RSS with minor noise
        for i in range(60):
            rss = 500.0 + 0.01 * (i % 5)
            detector.add_sample(rss)

        result = detector.analyze()
        assert result.is_leaking is False, (
            f"Steady state should not flag leak: slope={result.slope_mb_per_sample:.4f}"
        )

    def test_leak_detector_through_aggregator(self):
        """Feed leak-like data through AggregatorAnalyzer and verify the
        timeline shows growth suitable for leak detection.
        """
        analyzer = AggregatorAnalyzer(window_sec=120)

        # Simulate growing memory over time
        for i in range(60):
            raw = RawMetrics(
                ts_ms=int(time.time() * 1000) + i * 1000,
                cpu_percent=30.0 + (i % 3),
                mem_used_mb=200.0 + i * 5.0,  # grows by 5MB per sample
                mem_total_mb=4096.0,
                gpu_percent=None,
                gpu_mem_used_mb=None,
                temperature_c=45.0,
                probe_name="dummy",
                status="ok",
                latency_ms=0.01,
            )
            analyzer.ingest_metrics(raw)

        summary = analyzer.get_summary()

        # Verify the timeline shows growth
        mem_timeline = summary.timeline_mem_used_mb
        assert len(mem_timeline) >= 50, f"Expected >= 50 timeline points, got {len(mem_timeline)}"

        # First mem value should be significantly less than last
        first_mem = mem_timeline[0]
        last_mem = mem_timeline[-1]
        assert last_mem > first_mem + 100, (
            f"Memory should show growth: first={first_mem:.0f}, last={last_mem:.0f}"
        )

        # Feed timeline through leak detector
        detector = RSSLeakDetector(window_size=100, slope_threshold_mb=2.0, min_r_squared=0.8)
        for mem in mem_timeline:
            detector.add_sample(mem)

        result = detector.analyze()
        assert result.is_leaking is True, (
            f"Growing memory timeline should detect leak: "
            f"slope={result.slope_mb_per_sample:.3f}, r2={result.r_squared:.3f}"
        )


class TestDebugBundleFromAlert:
    """test_debug_bundle_from_alert — trigger alert -> auto-generate debug bundle."""

    def test_debug_bundle_from_alert(self):
        """Set up AlertManager, trigger an alert, then generate a debug bundle."""
        # Set up alert manager
        alert_mgr = AlertManager()
        alert_mgr.add_rule(
            AlertRule(
                name="high_memory",
                metric="rss_mb",
                condition="gt",
                threshold=100.0,
                severity=AlertSeverity.ERROR,
                cooldown_sec=0,  # no cooldown for test
            )
        )

        # Trigger the alert
        alerts = alert_mgr.check_threshold("rss_mb", 150.0)
        assert len(alerts) >= 1, "Alert should have triggered"

        alert = alerts[0]
        assert alert.status == AlertStatus.ACTIVE
        assert alert.severity == AlertSeverity.ERROR

        # Generate debug bundle from the alert
        with tempfile.TemporaryDirectory(prefix="debug_bundle_test_") as tmpdir:
            generator = DebugBundleGenerator(output_dir=Path(tmpdir))
            bundle = generator.generate(alert)

            # Verify bundle contents
            assert len(bundle.files) == 4, (
                f"Expected 4 bundle files, got {len(bundle.files)}"
            )
            assert bundle.total_size_bytes > 0, "Bundle should have non-zero size"
            assert bundle.generation_time_sec < 1.0, (
                f"Bundle generation took {bundle.generation_time_sec:.3f}s, should be < 1s"
            )

            # Verify all files exist and are non-empty
            for fpath in bundle.files:
                assert fpath.is_file(), f"Bundle file missing: {fpath}"
                assert fpath.stat().st_size > 0, f"Bundle file empty: {fpath}"

            # Verify bundle directory structure
            bundle_dir = Path(tmpdir) / f"bundle_{alert.id}"
            assert bundle_dir.is_dir(), f"Bundle dir missing: {bundle_dir}"

            # Verify specific files
            status_file = bundle_dir / "process_status.txt"
            assert status_file.is_file()
            status_content = status_file.read_text(encoding="utf-8")
            assert "VmRSS" in status_content
            assert "Alert" in status_content

            maps_file = bundle_dir / "memory_maps.txt"
            assert maps_file.is_file()
            maps_content = maps_file.read_text(encoding="utf-8")
            assert "heap" in maps_content or "stack" in maps_content

            context_file = bundle_dir / "alert_context.json"
            assert context_file.is_file()
            context_data = json.loads(context_file.read_text(encoding="utf-8"))
            assert "alert" in context_data
            assert "pid" in context_data
            assert context_data["alert"]["rule_name"] == "high_memory"

            # Verify total size < 10MB (acceptance criteria)
            assert bundle.total_size_bytes < 10 * 1024 * 1024, (
                f"Bundle size {bundle.total_size_bytes} exceeds 10MB limit"
            )

    def test_multiple_alerts_generate_separate_bundles(self):
        """Multiple alerts should each get their own debug bundle."""
        alert_mgr = AlertManager()
        alert_mgr.add_rule(
            AlertRule(
                name="high_cpu",
                metric="cpu_percent",
                condition="gt",
                threshold=80.0,
                severity=AlertSeverity.WARNING,
                cooldown_sec=0,
            )
        )
        alert_mgr.add_rule(
            AlertRule(
                name="critical_temp",
                metric="temperature_c",
                condition="gt",
                threshold=90.0,
                severity=AlertSeverity.CRITICAL,
                cooldown_sec=0,
            )
        )

        # Trigger both alerts
        cpu_alerts = alert_mgr.check_threshold("cpu_percent", 95.0)
        temp_alerts = alert_mgr.check_threshold("temperature_c", 95.0)

        all_alerts = cpu_alerts + temp_alerts
        assert len(all_alerts) >= 2, f"Expected >= 2 alerts, got {len(all_alerts)}"

        with tempfile.TemporaryDirectory(prefix="multi_bundle_test_") as tmpdir:
            generator = DebugBundleGenerator(output_dir=Path(tmpdir))
            bundles = [generator.generate(alert) for alert in all_alerts]

            # Each bundle should have its own directory
            bundle_dirs = set()
            for bundle in bundles:
                assert len(bundle.files) == 4
                bundle_dirs.add(bundle.files[0].parent)

            assert len(bundle_dirs) == len(all_alerts), (
                f"Expected {len(all_alerts)} unique bundle dirs, got {len(bundle_dirs)}"
            )
