"""Tests for the DiagnosticEngine."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from ai_advisor.cooldown import CooldownTracker
from ai_advisor.engine import DiagnosticEngine
from ai_advisor.models import Diagnosis, DiagnosticRule
from ai_advisor.rules import DEFAULT_RULES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rule(
    name: str,
    condition,
    priority: str = "medium",
    category: str = "test",
) -> DiagnosticRule:
    return DiagnosticRule(
        name=name,
        category=category,
        priority=priority,
        condition=condition,
        suggestion="fix it",
        evidence_template="detected {temp_max_c}",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEngineReturnsList:
    def test_empty_summary_returns_empty_list(self) -> None:
        engine = DiagnosticEngine(cooldown_sec=0)
        result = engine.diagnose({})
        assert isinstance(result, list)
        assert len(result) == 0


class TestEngineMatchesRule:
    def test_triggers_thermal_warning(self) -> None:
        engine = DiagnosticEngine(cooldown_sec=0)
        summary: Dict[str, Any] = {"temp_max_c": 75}
        result = engine.diagnose(summary)
        names = [d.rule_name for d in result]
        assert "thermal_warning" in names
        diagnosis = next(d for d in result if d.rule_name == "thermal_warning")
        assert diagnosis.priority == "high"
        assert diagnosis.category == "thermal"


class TestEngineNoMatch:
    def test_no_thermal_at_50c(self) -> None:
        engine = DiagnosticEngine(cooldown_sec=0)
        summary: Dict[str, Any] = {"temp_max_c": 50}
        result = engine.diagnose(summary)
        names = [d.rule_name for d in result]
        assert "thermal_warning" not in names
        assert "thermal_throttling" not in names


class TestCooldownPreventsDuplicate:
    def test_same_rule_not_repeated_within_cooldown(self) -> None:
        engine = DiagnosticEngine(cooldown_sec=9999)
        summary: Dict[str, Any] = {"temp_max_c": 75}
        first = engine.diagnose(summary)
        second = engine.diagnose(summary)
        assert len(first) > 0
        assert len(second) == 0


class TestPrioritySorting:
    def test_critical_before_high_before_medium(self) -> None:
        # thermal_throttling is critical; thermal_warning is high; quantization is medium
        engine = DiagnosticEngine(cooldown_sec=0)
        summary: Dict[str, Any] = {
            "temp_max_c": 85,
            "gpu_util": 20,       # triggers thermal_throttling (critical)
            "gpu_mem_percent": 90,  # triggers quantization_opportunity (medium)
        }
        result = engine.diagnose(summary)
        priorities = [d.priority for d in result]
        # Ensure all criticals come before all highs, and highs before mediums
        critical_idx = [i for i, p in enumerate(priorities) if p == "critical"]
        high_idx = [i for i, p in enumerate(priorities) if p == "high"]
        medium_idx = [i for i, p in enumerate(priorities) if p == "medium"]
        if critical_idx and high_idx:
            assert max(critical_idx) < min(high_idx)
        if high_idx and medium_idx:
            assert max(high_idx) < min(medium_idx)


class TestRuleExceptionHandled:
    def test_broken_rule_does_not_crash_engine(self) -> None:
        def _broken(_s: Dict[str, Any]) -> bool:
            raise RuntimeError("boom")

        broken = _make_rule("broken", _broken, priority="critical")
        engine = DiagnosticEngine(rules=[broken], cooldown_sec=0)
        result = engine.diagnose({"temp_max_c": 100})
        assert result == []


class TestAllRulesLoaded:
    def test_at_least_10_rules(self) -> None:
        assert len(DEFAULT_RULES) >= 10
