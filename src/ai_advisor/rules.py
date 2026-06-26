"""Built-in diagnostic rules for embedded AI inference monitoring."""

from __future__ import annotations

from typing import Any, Dict, List

from .models import DiagnosticRule


def _f(d: Dict[str, Any], key: str, default: float = 0.0) -> float:
    """Safely extract a float value from *d*."""
    v = d.get(key)
    return float(v) if v is not None else default


# ---------------------------------------------------------------------------
# Thermal rules
# ---------------------------------------------------------------------------

def _thermal_throttling(s: Dict[str, Any]) -> bool:
    """temp_max_c > 80 and gpu_util < 50 → likely thermal throttling."""
    return _f(s, "temp_max_c") > 80 and _f(s, "gpu_util") < 50


def _thermal_warning(s: Dict[str, Any]) -> bool:
    """70 < temp_max_c <= 80."""
    temp = _f(s, "temp_max_c")
    return 70 < temp <= 80


def _thermal_rising_trend(_s: Dict[str, Any]) -> bool:
    """Placeholder — requires temperature history integration."""
    return False


# ---------------------------------------------------------------------------
# Bottleneck rules
# ---------------------------------------------------------------------------

def _gpu_bound(s: Dict[str, Any]) -> bool:
    """gpu_percent > 90 and cpu_avg < 30."""
    return _f(s, "gpu_percent") > 90 and _f(s, "cpu_avg") < 30


def _cpu_bound(s: Dict[str, Any]) -> bool:
    """cpu_avg > 80 and gpu_percent < 50."""
    return _f(s, "cpu_avg") > 80 and _f(s, "gpu_percent") < 50


def _memory_bound(s: Dict[str, Any]) -> bool:
    """Simplified: gpu_percent > 80."""
    return _f(s, "gpu_percent") > 80


def _preprocessing_stall(s: Dict[str, Any]) -> bool:
    """preprocess_ratio > 0.3."""
    return _f(s, "preprocess_ratio") > 0.3


# ---------------------------------------------------------------------------
# Resource rules
# ---------------------------------------------------------------------------

def _memory_leak_risk(_s: Dict[str, Any]) -> bool:
    """Placeholder — requires memory detector integration."""
    return False


def _high_cpu_overhead(s: Dict[str, Any]) -> bool:
    """monitor_cpu_percent > 3."""
    return _f(s, "monitor_cpu_percent") > 3


# ---------------------------------------------------------------------------
# Deployment rules
# ---------------------------------------------------------------------------

def _power_budget_exceeded(_s: Dict[str, Any]) -> bool:
    """Placeholder — requires power budget configuration."""
    return False


def _batch_size_optimization(_s: Dict[str, Any]) -> bool:
    """Placeholder — requires batch-size configuration."""
    return False


def _quantization_opportunity(s: Dict[str, Any]) -> bool:
    """gpu_mem_percent > 80."""
    return _f(s, "gpu_mem_percent") > 80


# ---------------------------------------------------------------------------
# Rule catalogue
# ---------------------------------------------------------------------------

DEFAULT_RULES: List[DiagnosticRule] = [
    DiagnosticRule(
        name="thermal_throttling",
        category="thermal",
        priority="critical",
        condition=_thermal_throttling,
        suggestion="降低负载或改善散热，温度过高可能导致 GPU 降频",
        evidence_template="温度 {temp_max_c:.1f}°C 超过阈值 80°C，GPU 利用率低",
    ),
    DiagnosticRule(
        name="thermal_warning",
        category="thermal",
        priority="high",
        condition=_thermal_warning,
        suggestion="监控温度趋势，必要时降低推理频率",
        evidence_template="温度 {temp_max_c:.1f}°C 处于 70-80°C 预警区间",
    ),
    DiagnosticRule(
        name="thermal_rising_trend",
        category="thermal",
        priority="medium",
        condition=_thermal_rising_trend,
        suggestion="持续升温趋势，建议检查散热",
        evidence_template="温度呈上升趋势",
    ),
    DiagnosticRule(
        name="gpu_bound",
        category="bottleneck",
        priority="high",
        condition=_gpu_bound,
        suggestion="GPU 瓶颈：考虑使用 TensorRT 加速或降低模型复杂度",
        evidence_template="GPU {gpu_percent:.0f}% 但 CPU 仅 {cpu_avg:.0f}%",
    ),
    DiagnosticRule(
        name="cpu_bound",
        category="bottleneck",
        priority="high",
        condition=_cpu_bound,
        suggestion="CPU 瓶颈：优化预处理逻辑或使用多线程",
        evidence_template="CPU {cpu_avg:.0f}% 但 GPU 仅 {gpu_percent:.0f}%",
    ),
    DiagnosticRule(
        name="memory_bound",
        category="bottleneck",
        priority="medium",
        condition=_memory_bound,
        suggestion="内存/显存可能不足，考虑减小 batch size",
        evidence_template="GPU 利用率 {gpu_percent:.0f}%，可能存在内存瓶颈",
    ),
    DiagnosticRule(
        name="preprocessing_stall",
        category="bottleneck",
        priority="medium",
        condition=_preprocessing_stall,
        suggestion="预处理占比过高，优化数据管道",
        evidence_template="预处理占比 {preprocess_ratio:.1%}",
    ),
    DiagnosticRule(
        name="memory_leak_risk",
        category="resource",
        priority="high",
        condition=_memory_leak_risk,
        suggestion="检测到内存持续增长，可能存在泄漏",
        evidence_template="内存使用持续上升",
    ),
    DiagnosticRule(
        name="high_cpu_overhead",
        category="resource",
        priority="medium",
        condition=_high_cpu_overhead,
        suggestion="监控工具自身 CPU 开销过高，降低采样频率",
        evidence_template="监控进程 CPU 占用 {monitor_cpu_percent:.1f}%",
    ),
    DiagnosticRule(
        name="power_budget_exceeded",
        category="deployment",
        priority="high",
        condition=_power_budget_exceeded,
        suggestion="功耗超出预算，降低推理频率或使用低功耗模式",
        evidence_template="功耗超出预算",
    ),
    DiagnosticRule(
        name="batch_size_optimization",
        category="deployment",
        priority="medium",
        condition=_batch_size_optimization,
        suggestion="调整 batch size 可能提升吞吐量",
        evidence_template="当前 batch size 可能不是最优",
    ),
    DiagnosticRule(
        name="quantization_opportunity",
        category="deployment",
        priority="medium",
        condition=_quantization_opportunity,
        suggestion="显存使用率高，考虑模型量化 (INT8/FP16)",
        evidence_template="GPU 显存使用 {gpu_mem_percent:.0f}%",
    ),
]
