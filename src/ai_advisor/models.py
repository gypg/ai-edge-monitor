"""Diagnostic data models — immutable dataclasses for rules and diagnoses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict


@dataclass(frozen=True)
class DiagnosticRule:
    """A single diagnostic rule that can fire on a metrics summary."""

    name: str
    category: str  # "thermal" | "bottleneck" | "resource" | "deployment"
    priority: str  # "critical" | "high" | "medium" | "low"
    condition: Callable[[Dict[str, Any]], bool]
    suggestion: str
    evidence_template: str  # e.g. "温度 {temp_max_c:.1f}°C 超过阈值 80°C"


@dataclass(frozen=True)
class Diagnosis:
    """Result of a single rule matching against a metrics summary."""

    rule_name: str
    category: str
    priority: str
    suggestion: str
    evidence: str
    metrics_snapshot: Dict[str, Any] = field(default_factory=dict)
