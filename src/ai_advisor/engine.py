"""Diagnostic engine — evaluates rules against metrics and returns ranked diagnoses."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .cooldown import CooldownTracker
from .models import Diagnosis, DiagnosticRule
from .rules import DEFAULT_RULES

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class DiagnosticEngine:
    """Runs a set of :class:`DiagnosticRule` against a metrics summary."""

    def __init__(
        self,
        rules: Optional[List[DiagnosticRule]] = None,
        cooldown_sec: float = 60.0,
    ) -> None:
        self._rules = rules if rules is not None else list(DEFAULT_RULES)
        self._cooldown = CooldownTracker()
        self._cooldown_sec = cooldown_sec

    def diagnose(self, summary: Dict[str, Any]) -> List[Diagnosis]:
        """Return all matching diagnoses, sorted by priority (critical first)."""
        results: List[Diagnosis] = []
        for rule in self._rules:
            try:
                if rule.condition(summary) and self._cooldown.should_fire(
                    rule.name, self._cooldown_sec
                ):
                    evidence = (
                        rule.evidence_template.format(**summary)
                        if summary
                        else rule.evidence_template
                    )
                    results.append(
                        Diagnosis(
                            rule_name=rule.name,
                            category=rule.category,
                            priority=rule.priority,
                            suggestion=rule.suggestion,
                            evidence=evidence,
                            metrics_snapshot=dict(summary),
                        )
                    )
            except Exception:
                continue  # Never let a broken rule crash the engine
        results.sort(key=lambda d: _PRIORITY_ORDER.get(d.priority, 99))
        return results
