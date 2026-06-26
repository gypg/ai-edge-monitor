"""数据质量处理模块

提供以下功能：
1. 缺失值策略：处理缺失的指标数据
2. 异常值处理：检测和处理异常值
3. 数据校验：验证数据的完整性和有效性
4. 数据标准化：统一数据格式和单位
"""

from __future__ import annotations

import math
import statistics
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple, Union

from aggregator_analyzer import WindowSummary


@dataclass
class QualityConfig:
    """数据质量配置"""
    # 缺失值策略
    missing_value_strategy: str = "forward_fill"  # forward_fill, interpolation, zero, drop
    max_missing_ratio: float = 0.3  # 最大缺失比例
    
    # 异常值检测
    outlier_detection: bool = True
    outlier_method: str = "iqr"  # iqr, zscore, percentile
    outlier_threshold: float = 1.5  # IQR 倍数或 Z-score 阈值
    
    # 数据校验
    validate_ranges: bool = True
    cpu_range: Tuple[float, float] = (0.0, 100.0)
    memory_range: Tuple[float, float] = (0.0, float('inf'))
    temperature_range: Tuple[float, float] = (-40.0, 150.0)
    power_range: Tuple[float, float] = (0.0, 1000.0)
    
    # 数据标准化
    normalize_timestamps: bool = True
    timestamp_unit: str = "ms"  # ms, s


class DataQualityProcessor:
    """数据质量处理器"""
    
    def __init__(
        self,
        config: Optional[QualityConfig] = None,
        max_history: int = 1000,
    ):
        self.config = config or QualityConfig()
        self._max_history = max_history
        self._history: Dict[str, Deque[float]] = {
            "cpu": deque(maxlen=self._max_history),
            "memory": deque(maxlen=self._max_history),
            "temperature": deque(maxlen=self._max_history),
            "power": deque(maxlen=self._max_history),
        }
    
    def process_metrics(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """处理单个指标数据"""
        processed = dict(metrics)
        
        # 1. 处理缺失值
        processed = self._handle_missing_values(processed)
        
        # 2. 检测和处理异常值
        if self.config.outlier_detection:
            processed = self._handle_outliers(processed)
        
        # 3. 数据校验
        if self.config.validate_ranges:
            processed = self._validate_ranges(processed)
        
        # 4. 更新历史数据
        self._update_history(processed)
        
        return processed
    
    def process_window_summary(self, summary: WindowSummary) -> WindowSummary:
        """处理窗口摘要数据"""
        # 创建副本
        processed = WindowSummary(
            window_sec=summary.window_sec,
            sample_count_metrics=summary.sample_count_metrics,
            sample_count_power=summary.sample_count_power,
        )
        
        # 处理 CPU 数据
        processed.cpu_avg = self._process_value(summary.cpu_avg, "cpu")
        processed.cpu_p95 = self._process_value(summary.cpu_p95, "cpu")
        processed.cpu_max = self._process_value(summary.cpu_max, "cpu")
        
        # 处理内存数据
        processed.mem_used_avg_mb = self._process_value(summary.mem_used_avg_mb, "memory")
        processed.mem_used_max_mb = self._process_value(summary.mem_used_max_mb, "memory")
        processed.mem_total_mb = self._process_value(summary.mem_total_mb, "memory")
        
        # 处理温度数据
        processed.temp_max_c = self._process_value(summary.temp_max_c, "temperature")
        
        # 处理功耗数据
        processed.power_avg_watt = self._process_value(summary.power_avg_watt, "power")
        processed.power_p95_watt = self._process_value(summary.power_p95_watt, "power")
        processed.power_max_watt = self._process_value(summary.power_max_watt, "power")
        processed.energy_joule = summary.energy_joule
        processed.power_quality_worst = summary.power_quality_worst
        processed.power_source_name = summary.power_source_name
        processed.power_fail_rate_max = summary.power_fail_rate_max
        
        # 处理时间线数据
        processed.timeline_ts_ms = summary.timeline_ts_ms
        processed.timeline_cpu = self._process_timeline(summary.timeline_cpu, "cpu")
        processed.timeline_mem_used_mb = self._process_timeline(summary.timeline_mem_used_mb, "memory")
        processed.timeline_power_ts_ms = summary.timeline_power_ts_ms
        processed.timeline_power_watt = self._process_timeline(summary.timeline_power_watt, "power")
        
        return processed
    
    def _handle_missing_values(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """处理缺失值"""
        processed = dict(metrics)
        
        # 检查并处理各个字段
        for field in ["cpu_percent", "mem_used_mb", "mem_total_mb", "temperature_c", "gpu_percent"]:
            value = processed.get(field)
            
            if value is None:
                # 根据策略处理缺失值
                if self.config.missing_value_strategy == "forward_fill":
                    # 使用历史值填充
                    history_key = self._get_history_key(field)
                    if history_key and self._history[history_key]:
                        processed[field] = self._history[history_key][-1]
                    else:
                        processed[field] = 0.0
                
                elif self.config.missing_value_strategy == "interpolation":
                    # 线性插值
                    history_key = self._get_history_key(field)
                    if history_key and len(self._history[history_key]) >= 2:
                        last_two = self._history[history_key][-2:]
                        processed[field] = (last_two[0] + last_two[1]) / 2
                    else:
                        processed[field] = 0.0
                
                elif self.config.missing_value_strategy == "zero":
                    processed[field] = 0.0
                
                elif self.config.missing_value_strategy == "drop":
                    # 标记为需要丢弃
                    processed["_drop"] = True
        
        return processed
    
    def _handle_outliers(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """处理异常值"""
        processed = dict(metrics)
        
        for field in ["cpu_percent", "mem_used_mb", "temperature_c", "gpu_percent"]:
            value = processed.get(field)
            if value is None:
                continue
            
            history_key = self._get_history_key(field)
            if not history_key or len(self._history[history_key]) < 10:
                continue
            
            # 检测异常值
            is_outlier = self._detect_outlier(value, self._history[history_key])
            
            if is_outlier:
                # 使用历史中位数替换异常值
                median_value = statistics.median(self._history[history_key])
                processed[field] = median_value
                processed[f"{field}_outlier"] = True
        
        return processed
    
    def _detect_outlier(self, value: float, history: List[float]) -> bool:
        """检测异常值"""
        if len(history) < 10:
            return False
        
        if self.config.outlier_method == "iqr":
            # IQR 方法
            sorted_history = sorted(history)
            n = len(sorted_history)
            q1 = sorted_history[n // 4]
            q3 = sorted_history[3 * n // 4]
            iqr = q3 - q1
            lower_bound = q1 - self.config.outlier_threshold * iqr
            upper_bound = q3 + self.config.outlier_threshold * iqr
            return value < lower_bound or value > upper_bound
        
        elif self.config.outlier_method == "zscore":
            # Z-score 方法
            mean_val = statistics.mean(history)
            std_val = statistics.stdev(history)
            if std_val == 0:
                return False
            z_score = abs(value - mean_val) / std_val
            return z_score > self.config.outlier_threshold
        
        elif self.config.outlier_method == "percentile":
            # 百分位数方法
            sorted_history = sorted(history)
            n = len(sorted_history)
            lower_percentile = sorted_history[int(n * 0.05)]
            upper_percentile = sorted_history[int(n * 0.95)]
            return value < lower_percentile or value > upper_percentile
        
        return False
    
    def _validate_ranges(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """验证数据范围"""
        processed = dict(metrics)
        
        # CPU 范围验证
        cpu = processed.get("cpu_percent")
        if cpu is not None:
            processed["cpu_percent"] = max(
                self.config.cpu_range[0],
                min(self.config.cpu_range[1], cpu)
            )
        
        # 内存范围验证
        mem = processed.get("mem_used_mb")
        if mem is not None:
            processed["mem_used_mb"] = max(
                self.config.memory_range[0],
                min(self.config.memory_range[1], mem)
            )
        
        # 温度范围验证
        temp = processed.get("temperature_c")
        if temp is not None:
            processed["temperature_c"] = max(
                self.config.temperature_range[0],
                min(self.config.temperature_range[1], temp)
            )
        
        # 功耗范围验证
        power = processed.get("power_watt")
        if power is not None:
            processed["power_watt"] = max(
                self.config.power_range[0],
                min(self.config.power_range[1], power)
            )
        
        return processed
    
    def _process_value(self, value: Optional[float], history_key: str) -> Optional[float]:
        """处理单个值"""
        if value is None:
            return None
        
        # 异常值检测
        if self.config.outlier_detection and history_key in self._history:
            history = self._history[history_key]
            if len(history) >= 10:
                is_outlier = self._detect_outlier(value, history)
                if is_outlier:
                    return statistics.median(history)
        
        return value
    
    def _process_timeline(self, timeline: List[float], history_key: str) -> List[float]:
        """处理时间线数据"""
        if not timeline:
            return timeline
        
        processed = []
        for value in timeline:
            processed_value = self._process_value(value, history_key)
            processed.append(processed_value if processed_value is not None else 0.0)
        
        return processed
    
    def _update_history(self, metrics: Dict[str, Any]) -> None:
        """更新历史数据 (deque maxlen handles eviction in O(1))"""
        # CPU
        cpu = metrics.get("cpu_percent")
        if cpu is not None:
            self._history["cpu"].append(cpu)

        # 内存
        mem = metrics.get("mem_used_mb")
        if mem is not None:
            self._history["memory"].append(mem)

        # 温度
        temp = metrics.get("temperature_c")
        if temp is not None:
            self._history["temperature"].append(temp)

        # 功耗
        power = metrics.get("power_watt")
        if power is not None:
            self._history["power"].append(power)
    
    def _get_history_key(self, field: str) -> Optional[str]:
        """获取历史数据键"""
        mapping = {
            "cpu_percent": "cpu",
            "mem_used_mb": "memory",
            "mem_total_mb": "memory",
            "temperature_c": "temperature",
            "gpu_percent": "cpu",  # GPU 使用率也使用 CPU 历史
            "power_watt": "power",
        }
        return mapping.get(field)
    
    def get_quality_stats(self) -> Dict[str, Any]:
        """获取数据质量统计"""
        stats = {}
        
        for key, history in self._history.items():
            if history:
                stats[key] = {
                    "count": len(history),
                    "mean": statistics.mean(history),
                    "median": statistics.median(history),
                    "std": statistics.stdev(history) if len(history) > 1 else 0,
                    "min": min(history),
                    "max": max(history),
                }
        
        return stats
    
    def reset(self) -> None:
        """重置历史数据"""
        for key in self._history:
            self._history[key] = deque(maxlen=self._max_history)


class DataQualityValidator:
    """数据质量验证器"""
    
    def __init__(self, config: Optional[QualityConfig] = None):
        self.config = config or QualityConfig()
    
    def validate_metrics(self, metrics: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """验证指标数据"""
        errors = []
        
        # 检查必填字段
        required_fields = ["ts_ms", "cpu_percent", "mem_used_mb", "mem_total_mb"]
        for field in required_fields:
            if field not in metrics:
                errors.append(f"缺少必填字段: {field}")
        
        # 检查数据类型
        if "ts_ms" in metrics and not isinstance(metrics["ts_ms"], (int, float)):
            errors.append("ts_ms 必须是数字")
        
        if "cpu_percent" in metrics:
            cpu = metrics["cpu_percent"]
            if not isinstance(cpu, (int, float)):
                errors.append("cpu_percent 必须是数字")
            elif cpu < 0 or cpu > 100:
                errors.append(f"cpu_percent 超出范围: {cpu}")
        
        # 检查缺失值比例
        total_fields = len(required_fields)
        missing_fields = sum(1 for field in required_fields if field not in metrics or metrics[field] is None)
        missing_ratio = missing_fields / total_fields
        
        if missing_ratio > self.config.max_missing_ratio:
            errors.append(f"缺失值比例过高: {missing_ratio:.2%}")
        
        return len(errors) == 0, errors
    
    def validate_window_summary(self, summary: WindowSummary) -> Tuple[bool, List[str]]:
        """验证窗口摘要数据"""
        errors = []
        
        # 检查采样数量
        if summary.sample_count_metrics <= 0:
            errors.append("采样数量必须大于 0")
        
        # 检查 CPU 值范围
        if summary.cpu_avg is not None:
            if summary.cpu_avg < 0 or summary.cpu_avg > 100:
                errors.append(f"cpu_avg 超出范围: {summary.cpu_avg}")
        
        # 检查内存值范围
        if summary.mem_used_avg_mb is not None:
            if summary.mem_used_avg_mb < 0:
                errors.append(f"mem_used_avg_mb 不能为负: {summary.mem_used_avg_mb}")
        
        # 检查温度值范围
        if summary.temp_max_c is not None:
            if summary.temp_max_c < -40 or summary.temp_max_c > 150:
                errors.append(f"temp_max_c 超出范围: {summary.temp_max_c}")
        
        return len(errors) == 0, errors