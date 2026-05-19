# AI辅助嵌入式硬件监控系统 PRD 总览

## 1. 项目目标与边界
本项目面向 Jetson、Raspberry Pi、边缘计算盒子等设备，提供**轻量级、可扩展、低侵入**的硬件监控能力，服务于 AI 推理部署前后的性能评估。

核心目标：
- 实时采集 CPU/GPU/内存/功耗指标
- 提供统计分析与瓶颈定位线索
- 输出可视化结果用于快速对比与决策

硬约束（必须满足）：
- 监控自身 CPU 开销保持在个位数百分比
- 内存占用保持极小（默认目标 < 30MB，可配置）
- 不影响业务推理主流程的可感知性能

---

## 2. 模块拆分（10 个模块）

> 模块状态图例：✅ 骨架 + 测试已落地  · 🟡 PRD 已确立，未实现  · ⚪ 仅占位

1. **config_manager（配置管理）** ⚪
   统一管理采样周期、指标开关、输出策略、平台适配参数。

2. **platform_adapter（平台适配层）** ✅
   屏蔽不同硬件/OS 的差异，提供统一的 CPU/GPU/内存/温度等指标读取接口。**功耗采集职责已剥离至 power_monitor 模块**，本模块不再读取功耗。

3. **metrics_collector（指标采集器）** ✅
   `Collector` 实现 `start/stop` 生命周期，把 `RawMetrics` 与 `PowerStatsFrame` 分别推给 `aggregator_analyzer`，支持 `force_dummy` 测试模式与从配置字典加载偏好（`platform_prefer` / `power_prefer`）。

4. **power_monitor（功耗采集与统计）** ✅
   独立的功耗链路：以最低开销采集板级功耗（sysfs/jtop/tegrastats 优先级回退），在模块内部完成滑窗统计与能量估算，向上输出 `PowerSample` 与 `PowerStatsFrame`。详见 [power_monitor_detailed](./power_monitor_detailed.md)。

5. **sampler_scheduler（采样调度器）** ✅
   `PeriodicScheduler` 按 `cycle_period_sec / collect_duration_sec` 驱动 collector 执行采集会话，支持降级（`degraded_cycle_period_sec`）与可选报告生成；`stop()` 等待当前会话完成后再退出。

6. **aggregator_analyzer（聚合与分析）** ✅
   进行滑动窗口聚合、统计计算、异常阈值判断与瓶颈提示；同时消费 `power_monitor` 的标准化功耗统计快照，做跨指标联合分析。

7. **storage_exporter（存储与导出）** ⚪
   低开销落盘（CSV/JSONL），支持按批次写入与可选压缩；分别落盘 `MetricSnapshot`、`PowerSample`、`PowerStatsFrame`。

8. **visualization（可视化）** ✅
   `plot_report(summary, png_path)` + CLI；matplotlib 主路径，stdlib PNG 回退后端；JSON sidecar 同步落盘。

9. **runtime_guardian（运行守护）** ✅
   `RuntimeGuardian` 周期采样自身 CPU%/RSS，按滞回阈值（默认 cpu>3%/rss>50MB 进入降级、cpu<2%/rss<40MB 退出）触发 `on_degrade`/`on_recover` 回调；psutil 不可用时打 WARNING 自禁用，保留 `inject_test_load` 测试通道。

10. **app_orchestrator（应用编排入口）** ⚪
    CLI/主流程入口，负责模块装配、生命周期管理、模式切换。

---

## 3. 模块依赖关系

```text
app_orchestrator
  ├─ config_manager
  ├─ runtime_guardian ──(降级/恢复指令)──► power_monitor
  ├─ sampler_scheduler
  │    └─ metrics_collector
  │          └─ platform_adapter   # 不含功耗
  ├─ power_monitor                 # 独立功耗采集 + 内部统计
  ├─ aggregator_analyzer ◄── PowerStatsFrame ── power_monitor
  ├─ storage_exporter
  └─ visualization
```

依赖原则：
- 上层只依赖抽象接口，不直接触碰平台细节。
- 采集链路（adapter -> collector -> scheduler）保持最短路径。
- 功耗链路（`power_monitor` -> `aggregator_analyzer` / `storage_exporter`）独立于通用指标链路，避免功耗源故障影响主采样循环。
- 分析、存储、可视化尽量异步或批处理，避免阻塞采样主循环。

---

## 4. 数据流与控制流

### 4.1 数据流
1. `platform_adapter` 从系统接口读取 CPU/GPU/内存/温度等原始指标（`/proc`、`sysfs` 非功耗节点、`nvidia-smi`、`vcgencmd` 等）。**不再读取功耗。**
2. `metrics_collector` 统一字段、补齐时间戳、形成 `MetricSnapshot`（`power_watt` 字段保留为可选，仅由 power_monitor 的最新采样值在分析层旁路填充）。
3. `sampler_scheduler` 按固定节拍投递 `MetricSnapshot`。
4. `power_monitor` 以独立频率采集功耗（sysfs/jtop/tegrastats 优先级回退），内部维护滑动窗口，定期产出 `PowerSample` 与 `PowerStatsFrame`。
5. `aggregator_analyzer` 同时消费 `MetricSnapshot` 和 `PowerStatsFrame`，按时间戳对齐做联合分析，输出 `AnalysisFrame`。
6. `storage_exporter` 分批落盘 `MetricSnapshot` / `PowerSample` / `PowerStatsFrame` / `AnalysisFrame`；`visualization` 按需渲染图像。

```text
[platform_adapter]──cpu/gpu/mem/temp──►[metrics_collector]──MetricSnapshot──►[sampler_scheduler]──┐
                                                                                                  ├──►[aggregator_analyzer]──AnalysisFrame──►[storage_exporter]/[visualization]
[power_monitor]────────PowerStatsFrame / PowerSample──────────────────────────────────────────────┘
                                ▲
                                └── runtime_guardian（降级/恢复）
```

### 4.2 控制流
1. `app_orchestrator` 启动时加载配置并初始化模块（含 `power_monitor` 与 `runtime_guardian`）。
2. `runtime_guardian` 注册健康检查策略；按滞回阈值触发 `on_degrade` / `on_recover`，由 `scheduler.degrade()` / `scheduler.recover()` 接收，分别向 `sampler_scheduler` 与 `power_monitor` 下发降级指令。
3. `sampler_scheduler` (`PeriodicScheduler`) 周期性创建 `Collector` 会话；`Collector` 内部启动通用与功耗两个采样器；`power_monitor` 在 collector 内部维护滑窗 `PowerStats`。
4. 当资源超限时，`runtime_guardian` 触发降级（切换到 `degraded_cycle_period_sec`、可选 `degraded_pause_power`）；恢复后自动升回正常节拍。
5. 停止时统一 flush 缓冲并输出总结（power_monitor 需保证子进程类源——如 tegrastats——被回收；scheduler 等待当前会话结束再退出）。

---

## 5. 低开销采集设计策略

1. **采样频率分级**：
   - 高频（CPU/内存）：默认 500ms~1s
   - 低频（功耗/GPU）：默认 1s~2s

2. **批量写入与延迟计算**：
   - 采集线程仅做最小必要处理。
   - 聚合/导出采用批量与后台处理，减少频繁 I/O。

3. **零拷贝与对象复用**：
   - 使用轻量数据结构（`dataclass(slots=True)`）。
   - 复用缓冲区，避免高频 GC。

4. **可降级策略**：
   - 当监控开销超阈值，自动提升采样间隔。
   - 优先保留关键指标（CPU/内存），可临时关闭次要指标。

5. **最小依赖原则**：
   - 核心链路仅依赖标准库 + psutil（可选）。
   - 可视化模块与核心采样解耦，离线生成优先。

---

## 6. 关键数据结构（跨模块约定）

```python
from dataclasses import dataclass
from typing import Optional, Dict, Literal

Quality = Literal["raw", "derived", "estimated", "unavailable"]

@dataclass(slots=True)
class MetricSnapshot:
    ts_ms: int
    cpu_percent: float
    mem_used_mb: float
    mem_total_mb: float
    gpu_percent: Optional[float]
    gpu_mem_used_mb: Optional[float]
    # power_watt 不再由 platform_adapter 填充；保留为可选字段，
    # 仅由 aggregator_analyzer 在对齐 PowerStatsFrame 时填入展示值。
    power_watt: Optional[float]
    temperature_c: Optional[float]
    device_id: str
    tags: Dict[str, str]

@dataclass(slots=True)
class PowerStatsFrame:
    window_start_ms: int
    window_end_ms: int
    count: int
    avg_power_watt: Optional[float]
    p95_power_watt: Optional[float]
    max_power_watt: Optional[float]
    energy_joule: Optional[float]
    fail_rate: float
    fallback_count: int
    source_name: str
    quality: Quality

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
    power_quality: Optional[Quality]
    bottleneck_hint: Optional[str]
```

---

## 7. 当前描述中遗漏/需补充的关键设计点（风险提示）

1. **配置管理缺失（高优先）**
   建议在 `config_manager` 落地分层配置（默认值/文件/CLI 覆盖）与配置校验。

2. **持久化策略未明确（高优先）**
   建议在 `storage_exporter` 定义文件轮转、磁盘配额、异常中断恢复策略。

3. **错误自恢复机制未明确（高优先）**
   建议在 `runtime_guardian` 增加采集失败重试、模块熔断、自动降级恢复。

4. **跨平台兼容边界未明确（高优先）**
   建议在 `platform_adapter` 明确 Linux 优先、Jetson 专用能力探测、Raspberry Pi 兼容矩阵。

5. **时间同步与基准统一（中优先）**
   建议在 `sampler_scheduler` 使用 monotonic clock 驱动采样，wall clock 仅用于展示。

6. **数据质量与校准（中优先）**
   建议在 `metrics_collector` 加入缺失值策略、异常值夹断与数据源可信度标记。

7. **测试与基准标准未固化（高优先）**
   建议在各模块 PRD 中要求 micro-benchmark 与真实设备压测双轨验证。

---

## 8. 文档索引
- [config_manager](./config_manager.md)
- [platform_adapter](./platform_adapter.md)
- [metrics_collector](./metrics_collector.md)
- [power_monitor (overview)](./power_monitor_detailed.md)
- [sampler_scheduler](./sampler_scheduler.md)
- [aggregator_analyzer](./aggregator_analyzer.md)
- [storage_exporter](./storage_exporter.md)
- [visualization](./visualization.md)
- [runtime_guardian](./runtime_guardian.md)
- [app_orchestrator](./app_orchestrator.md)
- 变更说明：[add-power-monitor](../changelog/add-power-monitor.md)
- 变更说明：[add-platform-adapter](../changelog/add-platform-adapter.md)
- 变更说明：[add-aggregator-and-visualizer](../changelog/add-aggregator-and-visualizer.md)
- 变更说明：[add-infrastructure-modules](../changelog/add-infrastructure-modules.md)
