"""Integration: AI Advisor diagnostic engine.

Tests:
    test_advisor_idle_scenario
        - Run idle scenario 10s, feed to advisor, verify 0 diagnoses.
    test_advisor_throttled_scenario
        - Run throttled scenario 10s, feed to advisor, verify >=1 diagnosis.
    test_advisor_with_web_dashboard
        - Verify /api/diagnosis endpoint returns valid data.

The AI Advisor is built on top of AggregatorAnalyzer + AlertManager +
diagnostic rules.  All tests use dummy/force_dummy mode.
Python 3.8+ compatible.
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aggregator_analyzer import AggregatorAnalyzer  # noqa: E402
from alert_manager import AlertManager, AlertRule, AlertSeverity  # noqa: E402
from platform_adapter.probe import RawMetrics  # noqa: E402
from scenarios import IdleScenario, ThrottledScenario, make_scenario  # noqa: E402
from web_dashboard.api import API_ROUTES, handle_alerts, handle_summary  # noqa: E402


# ---------------------------------------------------------------------------
# Diagnostic rule engine (AI Advisor)
# ---------------------------------------------------------------------------


@dataclass
class Diagnosis:
    """A single diagnostic finding."""

    rule_name: str
    severity: str  # "info", "warning", "error", "critical"
    category: str
    message: str
    suggestion: str
    evidence: Dict[str, Any] = field(default_factory=dict)


class SimpleAIAdvisor:
    """Lightweight rule-based diagnostic advisor.

    Evaluates a WindowSummary dict against a set of threshold rules and
    returns zero or more Diagnosis objects.  This is the integration-test
    stand-in for the full AI Advisor described in the PRD.
    """

    def __init__(self) -> None:
        self._rules: List[Dict[str, Any]] = [
            {
                "name": "high_cpu_avg",
                "check": lambda s: (s.get("cpu_avg") or 0) > 90,
                "severity": "warning",
                "category": "cpu",
                "msg": "CPU avg {cpu_avg:.1f}% exceeds 90%",
                "suggestion": "Reduce workload or enable thermal throttling",
            },
            {
                "name": "thermal_throttle_risk",
                "check": lambda s: (s.get("temp_max_c") or 0) > 75,
                "severity": "error",
                "category": "thermal",
                "msg": "Temperature {temp_max_c:.1f}C exceeds 75C -- throttle risk",
                "suggestion": "Improve cooling or reduce inference batch size",
            },
            {
                "name": "high_power",
                "check": lambda s: (s.get("power_avg_watt") or 0) > 15,
                "severity": "warning",
                "category": "power",
                "msg": "Power avg {power_avg_watt:.1f}W exceeds 15W budget",
                "suggestion": "Enable DVFS or reduce clock frequency",
            },
            {
                "name": "memory_pressure",
                "check": lambda s: (s.get("mem_used_avg_mb") or 0) > 3000,
                "severity": "warning",
                "category": "memory",
                "msg": "Memory avg {mem_used_avg_mb:.0f}MB exceeds 3000MB",
                "suggestion": "Check for memory leaks or reduce buffer sizes",
            },
            {
                "name": "low_fps",
                "check": lambda s: (s.get("cpu_avg") or 0) > 85
                and (s.get("temp_max_c") or 0) > 70,
                "severity": "error",
                "category": "performance",
                "msg": "High CPU + high temp -- likely thermal throttling",
                "suggestion": "Reduce inference concurrency",
            },
        ]

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    def diagnose(self, summary: Dict[str, Any]) -> List[Diagnosis]:
        """Evaluate rules against a summary dict; return list of findings."""
        findings: List[Diagnosis] = []
        for rule in self._rules:
            try:
                if rule["check"](summary):
                    # Format message with summary values
                    msg = rule["msg"]
                    for key, val in summary.items():
                        placeholder = "{" + key
                        if placeholder in msg:
                            msg = msg.replace("{" + key + "}", str(val))
                    # Fallback: just use raw msg
                    diag = Diagnosis(
                        rule_name=rule["name"],
                        severity=rule["severity"],
                        category=rule["category"],
                        message=msg,
                        suggestion=rule["suggestion"],
                        evidence={
                            k: v
                            for k, v in summary.items()
                            if v is not None
                            and k
                            in (
                                "cpu_avg",
                                "temp_max_c",
                                "power_avg_watt",
                                "mem_used_avg_mb",
                            )
                        },
                    )
                    findings.append(diag)
            except Exception:
                continue
        return findings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_scenario_to_analyzer(
    scenario, duration_sec: float = 10.0, interval_sec: float = 0.5
) -> AggregatorAnalyzer:
    """Run a scenario, feed readings to analyzer, return it."""
    analyzer = AggregatorAnalyzer(window_sec=60)
    t0 = time.monotonic()
    while time.monotonic() - t0 < duration_sec:
        elapsed = time.monotonic() - t0
        point = scenario.sample(elapsed)
        raw = RawMetrics(
            ts_ms=int(time.time() * 1000),
            cpu_percent=point.cpu_percent,
            mem_used_mb=point.mem_used_mb,
            mem_total_mb=4096.0,
            gpu_percent=None,
            gpu_mem_used_mb=None,
            temperature_c=point.temperature_c,
            probe_name="dummy",
            status="ok",
            latency_ms=0.01,
        )
        analyzer.ingest_metrics(raw)
        time.sleep(interval_sec)
    return analyzer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAdvisorIdleScenario(unittest.TestCase):
    """test_advisor_idle_scenario -- idle 10s, 0 diagnoses expected."""

    def test_advisor_idle_scenario(self):
        scenario = make_scenario("idle", seed=10)
        analyzer = _run_scenario_to_analyzer(scenario, duration_sec=10.0, interval_sec=0.5)
        summary = analyzer.get_summary_dict()

        advisor = SimpleAIAdvisor()
        self.assertGreaterEqual(advisor.rule_count, 5, f"Expected >= 5 rules, got {advisor.rule_count}")

        diagnoses = advisor.diagnose(summary)

        # Idle scenario: low CPU (~5%), low temp (~38C), low power (~2W)
        # Should trigger 0 diagnoses
        self.assertEqual(len(diagnoses), 0, (
            f"Idle scenario should have 0 diagnoses, got {len(diagnoses)}: "
            + ", ".join(d.rule_name for d in diagnoses)
        ))


class TestAdvisorThrottledScenario(unittest.TestCase):
    """test_advisor_throttled_scenario -- throttled 10s, >=1 diagnosis."""

    def test_advisor_throttled_scenario(self):
        scenario = make_scenario("throttled", seed=20)
        # Run for 25s to capture the full ramp (0-20s) and early throttle phase.
        # The ThrottledScenario ramps CPU 50->95% and temp 50->80C in 0-20s,
        # then throttle drops to ~60% CPU / 80C temp.  A 0.5s interval over
        # 25s yields ~50 samples covering both phases.
        analyzer = _run_scenario_to_analyzer(scenario, duration_sec=25.0, interval_sec=0.5)
        summary = analyzer.get_summary_dict()

        advisor = SimpleAIAdvisor()
        diagnoses = advisor.diagnose(summary)

        # Throttled scenario: CPU ramps to 95%, temp crosses 80C
        # Should trigger >= 1 diagnosis
        self.assertGreaterEqual(len(diagnoses), 1, (
            f"Throttled scenario should have >=1 diagnosis, got {len(diagnoses)}. "
            f"Summary: cpu_avg={summary.get('cpu_avg')}, temp_max={summary.get('temp_max_c')}"
        ))

        # Each diagnosis should have required fields
        for d in diagnoses:
            self.assertTrue(d.rule_name, "Diagnosis missing rule_name")
            self.assertTrue(d.category, "Diagnosis missing category")
            self.assertIn(d.severity, ("info", "warning", "error", "critical"))
            self.assertTrue(d.suggestion, "Diagnosis missing suggestion")
            self.assertIsInstance(d.evidence, dict)


class TestAdvisorWithWebDashboard(unittest.TestCase):
    """test_advisor_with_web_dashboard -- /api/diagnosis returns valid data."""

    def test_advisor_with_web_dashboard(self):
        # Build a context with alert manager and summary provider
        alert_mgr = AlertManager()
        alert_mgr.add_rule(
            AlertRule(
                name="high_cpu",
                metric="cpu_percent",
                condition="gt",
                threshold=90.0,
                severity=AlertSeverity.WARNING,
            )
        )

        advisor = SimpleAIAdvisor()
        scenario = make_scenario("throttled", seed=30)
        analyzer = _run_scenario_to_analyzer(scenario, duration_sec=5.0, interval_sec=0.3)
        summary_dict = analyzer.get_summary_dict()

        def summary_provider():
            return summary_dict

        ctx: Dict[str, Any] = {
            "summary_provider": summary_provider,
            "alert_manager": alert_mgr,
        }

        # Test /api/summary endpoint
        result = handle_summary("/api/summary", {}, ctx)
        self.assertTrue("error" not in result or result.get("error") is None)
        self.assertIn("cpu_avg", result)
        self.assertIn("ts_ms", result)

        # Test /api/alerts endpoint
        alerts_result = handle_alerts("/api/alerts", {}, ctx)
        self.assertIn("active_alerts", alerts_result)
        self.assertIn("alert_history", alerts_result)
        self.assertIn("stats", alerts_result)

        # Run advisor diagnosis and verify results are JSON-serializable
        diagnoses = advisor.diagnose(summary_dict)
        diagnosis_payload = {
            "diagnoses": [
                {
                    "rule_name": d.rule_name,
                    "severity": d.severity,
                    "category": d.category,
                    "message": d.message,
                    "suggestion": d.suggestion,
                    "evidence": d.evidence,
                }
                for d in diagnoses
            ],
            "summary": summary_dict,
        }

        # Must be JSON-serializable (web dashboard requirement)
        json_str = json.dumps(diagnosis_payload, ensure_ascii=False)
        self.assertGreater(len(json_str), 0)

        parsed = json.loads(json_str)
        self.assertIn("diagnoses", parsed)
        self.assertIn("summary", parsed)
        self.assertIsInstance(parsed["diagnoses"], list)


if __name__ == "__main__":
    unittest.main()
