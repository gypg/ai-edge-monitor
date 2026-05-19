# metrics_collector 模块 PRD

## 1. 模块目标与定位
将平台原始指标转换为标准化快照，保证字段一致性与时间一致性。

## 2. 功能需求
- 从 `platform_adapter` 拉取数据。
- 标准化输出 `MetricSnapshot`。
- 填充时间戳、设备标识、标签。
- 缺失值与异常值处理（如 NaN 过滤、范围夹断）。

## 3. 非功能需求
- 每次转换开销 < 1ms（不含底层读取）。
- 仅做轻处理，不进行重计算。
- 内存对象复用，避免频繁分配。

## 4. 接口定义
```python
from dataclasses import dataclass
from typing import Optional, Dict

@dataclass(slots=True)
class MetricSnapshot:
    ts_ms: int
    cpu_percent: float
    mem_used_mb: float
    mem_total_mb: float
    gpu_percent: Optional[float]
    gpu_mem_used_mb: Optional[float]
    power_watt: Optional[float]
    temperature_c: Optional[float]
    device_id: str
    tags: Dict[str, str]

class MetricsCollector:
    def collect_once(self) -> MetricSnapshot: ...
    def sanitize(self, snap: MetricSnapshot) -> MetricSnapshot: ...
```

## 5. 与其他模块交互
- 被 `sampler_scheduler` 周期调用。
- 输出送入 `aggregator_analyzer` 与 `storage_exporter`。

## 6. 测试策略要点
- 字段完整性测试。
- 异常输入（负值、NaN、None）处理测试。
- 长时间运行下对象数量与 GC 行为监控。
