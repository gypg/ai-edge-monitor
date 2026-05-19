"""runtime_guardian — self-overhead watchdog with degrade hooks."""

from .guardian import GuardianConfig, RuntimeGuardian

__all__ = ["GuardianConfig", "RuntimeGuardian"]
