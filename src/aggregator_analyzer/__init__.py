"""aggregator_analyzer — windowed cross-source statistics.

See `docs/prd/aggregator_analyzer.md` for the cross-module contract.
"""

from .analyzer import AggregatorAnalyzer, WindowSummary

__all__ = ["AggregatorAnalyzer", "WindowSummary"]
