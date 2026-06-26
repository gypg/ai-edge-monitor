"""ai_advisor -- Rule-based diagnostic engine and deployment readiness scorer."""

from .engine import DiagnosticEngine
from .models import Diagnosis, DiagnosticRule
from .rules import DEFAULT_RULES
from .scorer import DeploymentAssessment, assess_deployment_readiness

__all__ = [
    "DiagnosticEngine",
    "Diagnosis",
    "DiagnosticRule",
    "DEFAULT_RULES",
    "DeploymentAssessment",
    "assess_deployment_readiness",
]
