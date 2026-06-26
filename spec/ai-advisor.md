# 子规格 — AI Advisor 自动诊断

> 关联验收标准：`acceptance-criteria.md` Phase 2

---

## 1. 概述

创建 `src/ai_advisor/` 模块，基于监控指标模式自动识别性能瓶颈并给出优化建议。

**不是 ML 模型**——是基于规则引擎的专家系统，未来可扩展为 ML 驱动。

---

## 2. 指标模式识别引擎

### 2.1 架构

```python
class DiagnosticEngine:
    """规则引擎：匹配指标模式 → 输出诊断结果。"""

    def __init__(self, rules: Optional[List[DiagnosticRule]] = None) -> None: ...
    def diagnose(self, summary: Dict[str, Any]) -> List[Diagnosis]: ...
```

### 2.2 诊断规则结构

```python
@dataclass
class DiagnosticRule:
    name: str
    category: str        # "thermal" | "bottleneck" | "resource" | "deployment"
    priority: str        # "critical" | "high" | "medium" | "low"
    condition: Callable[[Dict[str, Any]], bool]
    suggestion: str
    evidence_template: str  # 模板，{cpu_avg} 等变量会被替换
```

### 2.3 诊断结果

```python
@dataclass
class Diagnosis:
    rule_name: str
    category: str
    priority: str
    suggestion: str
    evidence: str        # 填充了实际指标值的证据描述
    metrics_snapshot: Dict[str, Any]  # 触发时的指标快照
```

---

## 3. 诊断规则库（≥ 10 条）

### 3.1 热管理类

| 规则名 | 条件 | 建议 |
|--------|------|------|
| `thermal_throttling` | `temp_max_c > 80 and gpu_util < 50` | "温度过高导致降频，建议改善散热或降低工作负载" |
| `thermal_warning` | `temp_max_c > 70 and temp_max_c <= 80` | "温度偏高，建议监控散热状况" |
| `thermal_rising_trend` | 连续 5 个窗口温度上升 > 2°C | "温度持续上升，可能出现热降频" |

### 3.2 推理瓶颈类

| 规则名 | 条件 | 建议 |
|--------|------|------|
| `gpu_bound` | `gpu_util > 90 and cpu_avg < 30` | "GPU 瓶颈，考虑模型量化(FP16/INT8)或减小 batch size" |
| `cpu_bound` | `cpu_avg > 80 and gpu_util < 50` | "CPU 瓶颈，考虑 GPU 预处理或 Neon SIMD 加速" |
| `memory_bound` | `gpu_util > 80 and fps_low` | "GPU 高负载但 FPS 低，可能内存瓶颈，考虑使用 FP16" |
| `preprocessing_stall` | `preprocess_ratio > 0.3` | "预处理占比过高，考虑 GPU 预处理或多线程流水线" |

### 3.3 资源管理类

| 规则名 | 条件 | 建议 |
|--------|------|------|
| `memory_leak_risk` | RSS 线性增长（R² > 0.8） | "疑似内存泄漏，建议检查推理框架的资源释放" |
| `high_cpu_overhead` | 监控工具 CPU > 3% | "监控开销过高，考虑增加采集间隔" |
| `power_budget_exceeded` | `power_avg_watt > budget` | "功耗超出预算，考虑降低推理频率或限制 GPU 时钟" |

### 3.4 部署建议类

| 规则名 | 条件 | 建议 |
|--------|------|------|
| `batch_size_optimization` | `fps < target and batch_size == 1` | "Batch size=1 可能未充分利用 GPU，尝试增大 batch" |
| `quantization_opportunity` | `gpu_mem_used > 0.8 * gpu_mem_total` | "GPU 显存紧张，考虑 INT8 量化或模型剪枝" |

---

## 4. 优化建议生成器

### 4.1 建议优先级排序

```python
PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

def sort_diagnoses(diagnoses: List[Diagnosis]) -> List[Diagnosis]:
    return sorted(diagnoses, key=lambda d: PRIORITY_ORDER[d.priority])
```

### 4.2 建议去重

同一 `rule_name` 在 `cooldown_sec`（默认 60s）内不重复输出。

---

## 5. 部署就绪评估

```python
def assess_deployment_readiness(
    summary: Dict[str, Any],
    target_fps: float,
    target_latency_ms: float,
    power_budget_watt: float,
    thermal_limit_c: float = 80.0,
) -> DeploymentAssessment:
    """评估当前设备是否能满足部署要求。"""
```

```python
@dataclass
class DeploymentAssessment:
    ready: bool
    score: int              # 0-100
    fps_headroom: float     # (target - actual) / target
    latency_headroom: float
    thermal_headroom: float
    power_headroom: float
    blocking_issues: List[str]  # 阻塞问题列表
    warnings: List[str]         # 警告列表
```

---

## 6. 测试策略

| 测试类型 | 位置 | 说明 |
|----------|------|------|
| 单元测试 | `tests/ai_advisor/test_engine.py` | 验证规则匹配、诊断输出、优先级排序 |
| 规则覆盖测试 | `tests/ai_advisor/test_rules.py` | 每条规则至少一个触发测试 + 一个不触发测试 |
| 性能测试 | `tests/ai_advisor/test_overhead.py` | 1000 次诊断 < 10ms 平均 |
| 集成测试 | `integration/test_ai_advisor.py` | idle/inference/throttled 场景验证 |
