# aggregator_analyzer 模块 PRD

## 1. 模块目标与定位
对原始采样数据进行窗口聚合与统计分析，输出性能画像与瓶颈提示。

> **新增（v3）**：实现已落地于 `src/aggregator_analyzer/`。`AggregatorAnalyzer` 提供 `ingest_metrics(RawMetrics)` / `ingest_power_stats(PowerStatsFrame)` / `get_summary()` / `get_summary_dict()`，内部维护两条独立的 deque + 共享锁。详见 [add-aggregator-and-visualizer 变更说明](../changelog/add-aggregator-and-visualizer.md)。

## 2. 功能需求
- 支持滑动窗口统计（均值、P50/P95、峰值）。
- 支持 CPU/GPU/内存/功耗关联分析。
- 生成轻量瓶颈规则提示（如 CPU 饱和、内存逼近上限、功耗异常）。
- 输出 `AnalysisFrame` 供展示与报告模块使用。
- **接收来自 `power_monitor` 的标准化功耗统计快照**（`PowerStatsFrame`）：本模块不再要求自行从原始功耗采样推导窗口指标，而是直接消费已经做过窗口统计、单位标准化与质量标注的功耗帧，并按时间戳与 `MetricSnapshot` 派生的 CPU/GPU/内存窗口对齐做联合分析。

## 3. 非功能需求
- O(1)/近 O(1) 增量更新，避免全量重算。
- 内存可控（窗口长度可配置）。
- 分析错误不影响采样主链路（包括 `power_monitor` 一侧的源故障，不应使本模块崩溃；缺帧时输出 `avg_power_watt=None` + 标注降级原因）。

## 4. 接口定义
```python
from dataclasses import dataclass
from typing import Optional

@dataclass(slots=True)
class AnalysisFrame:
    window_start_ms: int
    window_end_ms: int
    p50_cpu: float
    p95_cpu: float
    peak_mem_mb: float
    avg_power_watt: Optional[float]
    p95_power_watt: Optional[float]
    energy_joule: Optional[float]
    power_quality: Optional[str]   # raw / derived / estimated / unavailable
    power_source_name: Optional[str]
    bottleneck_hint: Optional[str]

class AggregatorAnalyzer:
    def ingest(self, snapshot: object) -> None: ...
    def ingest_power_stats(self, frame: "PowerStatsFrame") -> None: ...
    def flush_window(self) -> Optional[AnalysisFrame]: ...
    def reset(self) -> None: ...
```

### 4.1 输入接口约定
- `ingest(snapshot)`：来自 `sampler_scheduler` 的 `MetricSnapshot`（不再包含功耗字段）。
- `ingest_power_stats(frame)`：来自 `power_monitor` 的 `PowerStatsFrame`，已做滑窗统计、单位为 W/J，并携带 `quality` 与 `source_name`。
  - 入帧节奏由 `power_monitor.window_size` 决定（默认 60s 一帧），与本模块的分析窗口可不同步；本模块负责按时间戳对齐裁剪。
  - `quality == "estimated" | "unavailable"` 的帧仅参与展示与降级提示，不参与“功耗异常瓶颈规则”判定。

## 5. 与其他模块交互
- 输入来自 `sampler_scheduler` 推送的 `MetricSnapshot`（CPU/GPU/内存/温度）。
- 输入来自 `power_monitor` 推送/拉取的 `PowerStatsFrame`（功耗）。
- 输出给 `storage_exporter` 持久化、`visualization` 绘图。

## 6. 测试策略要点
- 统计正确性测试（与离线基准比对）。
- 窗口边界与空窗口测试。
- 异常数据鲁棒性测试。
- **跨源对齐测试**：`MetricSnapshot` 与 `PowerStatsFrame` 时间戳错位、丢帧、`quality` 降级时，`AnalysisFrame` 的功耗字段及瓶颈提示应正确降级而不抛错。
- **基线测试**：`tests/aggregator_analyzer/test_baseline.py` 在虚拟时钟下灌入 10000 帧，断言窗口剪裁不溢出且 RSS 增量 < 5MB。当前实测 0.11MB（开发机）。
- **端到端集成测试**：`integration/test_e2e_collect_to_report.py` 与 platform_adapter / power_monitor / visualizer 联动验证数据流闭环。当前实测 12 metrics + 13 power frames，PNG 报告输出正常。
