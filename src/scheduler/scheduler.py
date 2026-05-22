"""scheduler — periodic collection sessions + optional report writing.

`PeriodicScheduler` drives a `Collector` on a fixed cadence:

    every `cycle_period_sec` seconds, run `collect_duration_sec` seconds
    of collection; after each session, optionally render a report.

Cron-style schedules are accepted as a parsed minute spec (subset).
For now we implement the fixed-interval mode end-to-end and leave the
cron path hookable: a caller can pre-compute an iterator of "next
trigger" timestamps and pass them via `cycle_iter`.

The scheduler runs in a worker thread. `stop()` waits for the current
session to finish so reports never end up half-written. A scheduler with
`degrade_handler` set forwards external degrade/recover decisions to
itself (slower cycle, paused power) — `runtime_guardian` uses this.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from collector import Collector, CollectorConfig

LOG = logging.getLogger("scheduler")

ReportFn = Callable[[Dict[str, Any], Path], Any]


@dataclass
class ScheduleConfig:
    """Configuration for `PeriodicScheduler`.

    Fields:
        cycle_period_sec: seconds between session starts. Must be
            >= collect_duration_sec + a small idle margin.
        collect_duration_sec: how long each session collects.
        emit_report: whether to render a report after each session.
        report_dir: where reports go; one file per session.
        report_prefix: filename prefix; full path becomes
            `<report_dir>/<prefix>_<session_idx>.png`.
        degraded_cycle_period_sec: cycle period to use when the
            scheduler is degraded (e.g. by runtime_guardian).
        degraded_pause_power: when degraded, recreate the collector
            with the power source forced off (`power_prefer=()`).
            For the simple Dummy demo this just sets force_dummy=True.
    """

    cycle_period_sec: float = 30.0
    collect_duration_sec: float = 10.0
    emit_report: bool = True
    report_dir: Path = field(default_factory=lambda: Path("reports"))
    report_prefix: str = "session"
    degraded_cycle_period_sec: float = 60.0
    degraded_pause_power: bool = False


class PeriodicScheduler:
    """Scheduler that runs collection sessions on a fixed cadence."""

    def __init__(
        self,
        collector_config: CollectorConfig,
        schedule_config: ScheduleConfig,
        report_fn: Optional[ReportFn] = None,
        cycle_iter: Optional[Iterator[float]] = None,
    ) -> None:
        if schedule_config.cycle_period_sec < schedule_config.collect_duration_sec:
            raise ValueError("cycle_period_sec must be >= collect_duration_sec")
        self.collector_config = collector_config
        self.schedule_config = schedule_config
        self._report_fn = report_fn
        self._cycle_iter = cycle_iter

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._session_count = 0
        self._report_count = 0
        self._reports: List[Path] = []
        self._degraded = False
        self._collector: Optional[Collector] = None

    @property
    def session_count(self) -> int:
        with self._lock:
            return self._session_count

    @property
    def report_count(self) -> int:
        with self._lock:
            return self._report_count

    @property
    def reports(self) -> List[Path]:
        with self._lock:
            return list(self._reports)

    @property
    def is_degraded(self) -> bool:
        return self._degraded

    def schedule(self) -> None:
        """Start the scheduling loop in a background thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self, join_timeout: float = 5.0) -> None:
        """Signal stop and wait for the current session to finish."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=join_timeout)

    def degrade(self) -> None:
        """Switch to a slower cycle and (optionally) pause power."""
        if self._degraded:
            return
        self._degraded = True
        LOG.info(
            "scheduler degraded: switching to %.1fs cycle period",
            self.schedule_config.degraded_cycle_period_sec,
        )

    def recover(self) -> None:
        """Return to normal cadence."""
        if not self._degraded:
            return
        self._degraded = False
        LOG.info(
            "scheduler recovered: back to %.1fs cycle period", self.schedule_config.cycle_period_sec
        )

    def _current_cycle_period(self) -> float:
        if self._degraded:
            return self.schedule_config.degraded_cycle_period_sec
        return self.schedule_config.cycle_period_sec

    def _build_collector(self) -> Collector:
        cfg = self.collector_config
        if self._degraded and self.schedule_config.degraded_pause_power:
            cfg = CollectorConfig(
                interval_ms=cfg.interval_ms,
                platform_prefer=cfg.platform_prefer,
                power_prefer=(),  # force dummy power source
                force_dummy=True,
                power_window_size=cfg.power_window_size,
            )
        return Collector(cfg)

    def _run_loop(self) -> None:
        loop_started = time.monotonic()
        while not self._stop_event.is_set():
            session_start = time.monotonic()
            session_idx = self._session_count + 1
            collector = self._build_collector()
            self._collector = collector

            collect_for = self.schedule_config.collect_duration_sec
            LOG.info(
                "session %d start: probe=%s source=%s collect=%.1fs degraded=%s",
                session_idx,
                collector.probe_name,
                collector.power_source_name,
                collect_for,
                self._degraded,
            )
            collector.start()
            self._stop_event.wait(timeout=collect_for)
            collector.stop()

            with self._lock:
                self._session_count += 1

            if self.schedule_config.emit_report and self._report_fn is not None:
                report_dir = self.schedule_config.report_dir
                report_dir.mkdir(parents=True, exist_ok=True)
                report_path = (
                    report_dir / f"{self.schedule_config.report_prefix}" f"_{session_idx:03d}.png"
                )
                summary = collector.analyzer.get_summary_dict()
                try:
                    self._report_fn(summary, report_path)
                    with self._lock:
                        self._report_count += 1
                        self._reports.append(report_path)
                    LOG.info(
                        "session %d report: %s",
                        session_idx,
                        report_path,
                    )
                except Exception as exc:
                    LOG.error(
                        "session %d report failed: %s",
                        session_idx,
                        exc,
                    )

            self._collector = None

            if self._stop_event.is_set():
                break

            if self._cycle_iter is not None:
                try:
                    next_at = next(self._cycle_iter)
                    sleep_for = max(0.0, next_at - time.monotonic())
                except StopIteration:
                    break
            else:
                cycle = self._current_cycle_period()
                elapsed = time.monotonic() - session_start
                sleep_for = max(0.0, cycle - elapsed)
            if sleep_for > 0:
                self._stop_event.wait(timeout=sleep_for)

        LOG.info("scheduler loop exited (%.1fs total)", time.monotonic() - loop_started)
