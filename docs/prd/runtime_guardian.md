# runtime_guardian 模块 PRD

## 1. 模块目标与定位
持续监控监控器自身健康状态，确保“监控不干扰业务”的核心约束可被执行。

## 2. 功能需求
- 监控本进程 CPU、内存、队列积压、写入延迟。
- 当超阈值时触发降级策略（调低频率、关闭高成本指标、暂停可视化）。
- 采集链路异常时执行重试与熔断。
- 提供健康状态快照与告警事件。

## 3. 非功能需求
- 守护逻辑本身开销极低（低频运行，如 2s~5s 一次）。
- 降级与恢复策略可配置、可观测。
- 不与业务进程竞争高优先级资源。

## 4. 接口定义
```python
from dataclasses import dataclass

@dataclass(slots=True)
class HealthStatus:
    monitor_cpu_pct: float
    monitor_mem_mb: float
    queue_backlog: int
    degraded: bool
    reason: str

class RuntimeGuardian:
    def check(self) -> HealthStatus: ...
    def maybe_degrade(self) -> bool: ...
    def recover_if_possible(self) -> bool: ...
```

配置项建议：
- `cpu_overhead_limit_pct`
- `memory_limit_mb`
- `max_queue_backlog`
- `degrade_steps`

## 5. 与其他模块交互
- 向 `sampler_scheduler` 下发调频指令。
- 向 `storage_exporter` 下发限流/flush 指令。
- 向 `app_orchestrator` 报告健康状态与退出建议。

## 6. 测试策略要点
- 人工压测触发降级测试。
- 恢复条件达成后的自动恢复测试。
- 异常场景（采集失败、写入阻塞）自恢复测试。
