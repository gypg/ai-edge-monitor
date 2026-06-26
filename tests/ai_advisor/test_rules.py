"""Tests for individual diagnostic rules."""

from __future__ import annotations

import unittest
from typing import Any, Dict

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

class TestSafeFloatHelper(unittest.TestCase):
    def test_returns_value_when_present(self) -> None:
        self.assertEqual(_f({"x": 42}, "x"), 42.0)

    def test_returns_default_when_missing(self) -> None:
        self.assertEqual(_f({}, "x", default=1.0), 1.0)

    def test_returns_default_when_none(self) -> None:
        self.assertEqual(_f({"x": None}, "x"), 0.0)


# ---------------------------------------------------------------------------
# Thermal rules
# ---------------------------------------------------------------------------

class TestThermalThrottling(unittest.TestCase):
    def test_triggers_when_hot_and_gpu_idle(self) -> None:
        self.assertTrue(_thermal_throttling({"temp_max_c": 85, "gpu_util": 30}))

    def test_no_trigger_when_temp_ok(self) -> None:
        self.assertFalse(_thermal_throttling({"temp_max_c": 60, "gpu_util": 30}))

    def test_no_trigger_when_gpu_busy(self) -> None:
        self.assertFalse(_thermal_throttling({"temp_max_c": 85, "gpu_util": 70}))


class TestThermalWarning(unittest.TestCase):
    def test_triggers_in_70_80_range(self) -> None:
        self.assertTrue(_thermal_warning({"temp_max_c": 75}))

    def test_no_trigger_below_70(self) -> None:
        self.assertFalse(_thermal_warning({"temp_max_c": 65}))

    def test_no_trigger_above_80(self) -> None:
        self.assertFalse(_thermal_warning({"temp_max_c": 85}))

    def test_no_trigger_at_boundary_70(self) -> None:
        self.assertFalse(_thermal_warning({"temp_max_c": 70}))


class TestThermalRisingTrend(unittest.TestCase):
    def test_always_false_placeholder(self) -> None:
        self.assertFalse(_thermal_rising_trend({}))


# ---------------------------------------------------------------------------
# Bottleneck rules
# ---------------------------------------------------------------------------

class TestGpuBound(unittest.TestCase):
    def test_triggers_high_gpu_low_cpu(self) -> None:
        self.assertTrue(_gpu_bound({"gpu_percent": 95, "cpu_avg": 20}))

    def test_no_trigger_low_gpu(self) -> None:
        self.assertFalse(_gpu_bound({"gpu_percent": 50, "cpu_avg": 20}))

    def test_no_trigger_high_cpu(self) -> None:
        self.assertFalse(_gpu_bound({"gpu_percent": 95, "cpu_avg": 40}))


class TestCpuBound(unittest.TestCase):
    def test_triggers_high_cpu_low_gpu(self) -> None:
        self.assertTrue(_cpu_bound({"cpu_avg": 85, "gpu_percent": 30}))

    def test_no_trigger_low_cpu(self) -> None:
        self.assertFalse(_cpu_bound({"cpu_avg": 50, "gpu_percent": 30}))

    def test_no_trigger_high_gpu(self) -> None:
        self.assertFalse(_cpu_bound({"cpu_avg": 85, "gpu_percent": 70}))


class TestMemoryBound(unittest.TestCase):
    def test_triggers_high_gpu_percent(self) -> None:
        self.assertTrue(_memory_bound({"gpu_percent": 90}))

    def test_no_trigger_low_gpu_percent(self) -> None:
        self.assertFalse(_memory_bound({"gpu_percent": 50}))


class TestPreprocessingStall(unittest.TestCase):
    def test_triggers_high_ratio(self) -> None:
        self.assertTrue(_preprocessing_stall({"preprocess_ratio": 0.4}))

    def test_no_trigger_low_ratio(self) -> None:
        self.assertFalse(_preprocessing_stall({"preprocess_ratio": 0.1}))


# ---------------------------------------------------------------------------
# Resource rules
# ---------------------------------------------------------------------------

class TestMemoryLeakRisk(unittest.TestCase):
    def test_always_false_placeholder(self) -> None:
        self.assertFalse(_memory_leak_risk({}))


class TestHighCpuOverhead(unittest.TestCase):
    def test_triggers_above_3_percent(self) -> None:
        self.assertTrue(_high_cpu_overhead({"monitor_cpu_percent": 5}))

    def test_no_trigger_below_3_percent(self) -> None:
        self.assertFalse(_high_cpu_overhead({"monitor_cpu_percent": 1}))


# ---------------------------------------------------------------------------
# Deployment rules
# ---------------------------------------------------------------------------

class TestPowerBudgetExceeded(unittest.TestCase):
    def test_always_false_placeholder(self) -> None:
        self.assertFalse(_power_budget_exceeded({}))


class TestBatchSizeOptimization(unittest.TestCase):
    def test_always_false_placeholder(self) -> None:
        self.assertFalse(_batch_size_optimization({}))


class TestQuantizationOpportunity(unittest.TestCase):
    def test_triggers_high_gpu_mem(self) -> None:
        self.assertTrue(_quantization_opportunity({"gpu_mem_percent": 90}))

    def test_no_trigger_low_gpu_mem(self) -> None:
        self.assertFalse(_quantization_opportunity({"gpu_mem_percent": 50}))


# ---------------------------------------------------------------------------
# Rule catalogue
# ---------------------------------------------------------------------------

class TestRulesCount(unittest.TestCase):
    def test_at_least_10_rules(self) -> None:
        self.assertGreaterEqual(len(DEFAULT_RULES), 10)


if __name__ == "__main__":
    unittest.main()
