"""Tests for individual diagnostic rules."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from ai_advisor.rules import DEFAULT_RULES, _f

# Import rule condition functions directly for targeted testing
from ai_advisor.rules import (
    _thermal_throttling,
    _thermal_warning,
    _thermal_rising_trend,
    _gpu_bound,
    _cpu_bound,
    _memory_bound,
    _preprocessing_stall,
    _memory_leak_risk,
    _high_cpu_overhead,
    _power_budget_exceeded,
    _batch_size_optimization,
    _quantization_opportunity,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

class TestSafeFloatHelper:
    def test_returns_value_when_present(self) -> None:
        assert _f({"x": 42}, "x") == 42.0

    def test_returns_default_when_missing(self) -> None:
        assert _f({}, "x", default=1.0) == 1.0

    def test_returns_default_when_none(self) -> None:
        assert _f({"x": None}, "x") == 0.0


# ---------------------------------------------------------------------------
# Thermal rules
# ---------------------------------------------------------------------------

class TestThermalThrottling:
    def test_triggers_when_hot_and_gpu_idle(self) -> None:
        assert _thermal_throttling({"temp_max_c": 85, "gpu_util": 30}) is True

    def test_no_trigger_when_temp_ok(self) -> None:
        assert _thermal_throttling({"temp_max_c": 60, "gpu_util": 30}) is False

    def test_no_trigger_when_gpu_busy(self) -> None:
        assert _thermal_throttling({"temp_max_c": 85, "gpu_util": 70}) is False


class TestThermalWarning:
    def test_triggers_in_70_80_range(self) -> None:
        assert _thermal_warning({"temp_max_c": 75}) is True

    def test_no_trigger_below_70(self) -> None:
        assert _thermal_warning({"temp_max_c": 65}) is False

    def test_no_trigger_above_80(self) -> None:
        assert _thermal_warning({"temp_max_c": 85}) is False

    def test_no_trigger_at_boundary_70(self) -> None:
        assert _thermal_warning({"temp_max_c": 70}) is False


class TestThermalRisingTrend:
    def test_always_false_placeholder(self) -> None:
        assert _thermal_rising_trend({}) is False


# ---------------------------------------------------------------------------
# Bottleneck rules
# ---------------------------------------------------------------------------

class TestGpuBound:
    def test_triggers_high_gpu_low_cpu(self) -> None:
        assert _gpu_bound({"gpu_percent": 95, "cpu_avg": 20}) is True

    def test_no_trigger_low_gpu(self) -> None:
        assert _gpu_bound({"gpu_percent": 50, "cpu_avg": 20}) is False

    def test_no_trigger_high_cpu(self) -> None:
        assert _gpu_bound({"gpu_percent": 95, "cpu_avg": 40}) is False


class TestCpuBound:
    def test_triggers_high_cpu_low_gpu(self) -> None:
        assert _cpu_bound({"cpu_avg": 85, "gpu_percent": 30}) is True

    def test_no_trigger_low_cpu(self) -> None:
        assert _cpu_bound({"cpu_avg": 50, "gpu_percent": 30}) is False

    def test_no_trigger_high_gpu(self) -> None:
        assert _cpu_bound({"cpu_avg": 85, "gpu_percent": 70}) is False


class TestMemoryBound:
    def test_triggers_high_gpu_percent(self) -> None:
        assert _memory_bound({"gpu_percent": 90}) is True

    def test_no_trigger_low_gpu_percent(self) -> None:
        assert _memory_bound({"gpu_percent": 50}) is False


class TestPreprocessingStall:
    def test_triggers_high_ratio(self) -> None:
        assert _preprocessing_stall({"preprocess_ratio": 0.4}) is True

    def test_no_trigger_low_ratio(self) -> None:
        assert _preprocessing_stall({"preprocess_ratio": 0.1}) is False


# ---------------------------------------------------------------------------
# Resource rules
# ---------------------------------------------------------------------------

class TestMemoryLeakRisk:
    def test_always_false_placeholder(self) -> None:
        assert _memory_leak_risk({}) is False


class TestHighCpuOverhead:
    def test_triggers_above_3_percent(self) -> None:
        assert _high_cpu_overhead({"monitor_cpu_percent": 5}) is True

    def test_no_trigger_below_3_percent(self) -> None:
        assert _high_cpu_overhead({"monitor_cpu_percent": 1}) is False


# ---------------------------------------------------------------------------
# Deployment rules
# ---------------------------------------------------------------------------

class TestPowerBudgetExceeded:
    def test_always_false_placeholder(self) -> None:
        assert _power_budget_exceeded({}) is False


class TestBatchSizeOptimization:
    def test_always_false_placeholder(self) -> None:
        assert _batch_size_optimization({}) is False


class TestQuantizationOpportunity:
    def test_triggers_high_gpu_mem(self) -> None:
        assert _quantization_opportunity({"gpu_mem_percent": 90}) is True

    def test_no_trigger_low_gpu_mem(self) -> None:
        assert _quantization_opportunity({"gpu_mem_percent": 50}) is False


# ---------------------------------------------------------------------------
# Rule catalogue
# ---------------------------------------------------------------------------

class TestRulesCount:
    def test_at_least_10_rules(self) -> None:
        assert len(DEFAULT_RULES) >= 10
