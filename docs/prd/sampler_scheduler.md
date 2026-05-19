# sampler_scheduler 模块 PRD

## 1. 模块目标与定位
以稳定、低抖动的节拍驱动采样流程，控制采样频率与执行时序。

## 2. 功能需求
- 固定周期调度 `metrics_collector.collect_once()`。
- 支持多频率任务（例如功耗低频采样）。
- 支持开始、暂停、停止。
- 输出采样延迟与丢帧统计。

## 3. 非功能需求
- 时间基准使用 monotonic clock。
- 调度抖动尽量低（目标 p95 抖动 < 10% 采样间隔）。
- 调度逻辑开销极低，不做阻塞 I/O。

## 4. 接口定义
```python
from typing import Callable

class SamplerScheduler:
    def start(self, on_snapshot: Callable[[object], None]) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def stop(self) -> None: ...
    def set_interval(self, interval_ms: int) -> None: ...
```

## 5. 与其他模块交互
- 上游依赖 `config_manager` 获取采样间隔。
- 下游调用 `metrics_collector` 并将结果回调给 `aggregator_analyzer`/`storage_exporter`。
- 接收 `runtime_guardian` 的降级指令动态调频。

## 6. 测试策略要点
- 调度精度与抖动测试。
- 长时间运行稳定性测试（>24h）。
- 动态调频与暂停恢复正确性测试。
