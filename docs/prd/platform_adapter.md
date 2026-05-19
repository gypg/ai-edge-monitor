# platform_adapter 模块 PRD

## 1. 模块目标与定位
提供统一硬件指标读取抽象，屏蔽 Jetson/Raspberry Pi/通用 Linux 的底层差异。

> **职责边界变更（v2）**：功耗采集职责已剥离至 `power_monitor` 模块。本模块不再负责板级功耗 (`power_watt` / `voltage_v` / `current_a`) 的读取与单位标准化。能力探测中保留 `has_power_sensor` 字段仅作为参考信息，不再驱动本模块自身的采集逻辑。详见 [power_monitor_detailed](./power_monitor_detailed.md) 与 [add-power-monitor 变更说明](../changelog/add-power-monitor.md)。

> **新增（v3）**：模块代码骨架已落地于 `src/platform_adapter/`，包含 `PlatformProbe` 抽象、`DummyProbe`/`ProcfsProbe`/`PsutilProbe` 三种实现、自定义 `PlatformSampler`，以及 `select_default_probe(prefer)` 探测链。详见 [add-platform-adapter 变更说明](../changelog/add-platform-adapter.md)。

## 2. 功能需求
- **能力探测**：识别 CPU/内存/GPU/温度传感器可用性，并继续上报 `has_power_sensor`（仅信息字段，由 `power_monitor` 用作回退判断的辅助参考，不在本模块内消费）。
- **统一读取 API**：CPU 利用率、内存（已用 / 总量）、GPU 利用率与显存、CPU/SoC 温度，统一经 `read_metrics()` 输出 `RawMetrics`。
- **多 backend**：
  - `procfs`（Linux 首选，stdlib）：`/proc/stat`（CPU 增量法）、`/proc/meminfo`、`/sys/class/thermal`；
  - `psutil`（跨平台回退）：CPU/内存/温度；
  - `dummy`（开发机/测试）：稳定合成值；
  - 待补：Jetson（jtop / `tegrastats` 仅供温度+GPU，不复用其功耗轨）、NVML、`vcgencmd`。
- **失败语义**：数据读取失败返回 `status ∈ {io_error, parse_error, not_supported, partial}`，绝不抛出未处理异常。
- **不再**：直接读取 `power_now` / `current_now` / `voltage_now`、调用 `tegrastats`/`jtop` 获取功耗轨——这些路径全部由 `power_monitor` 拥有，避免双方重复采集与争抢同一文件描述符。

## 3. 非功能需求
- 单次 `read_metrics()` 调用 CPU 时间：P95 < 5ms（procfs 路径），psutil 路径放宽到 < 8ms。
- 不执行高频 shell 子进程（需缓存探测结果，优先直接文件读取）。
- 与 `power_monitor` 同等的低开销门禁：DummyProbe 30s @100ms 空跑，CPU 时间增量 < 5ms、RSS 增量 < 5MB（基线测试已实现，详见 §6）。
- 跨平台策略可扩展（插件式 backend）。

## 4. 接口定义
```python
from dataclasses import dataclass, field
from typing import Dict, Literal, Optional

ReadStatus = Literal["ok", "io_error", "parse_error", "not_supported", "partial"]

@dataclass
class PlatformCaps:
    has_cpu: bool = True
    has_mem: bool = True
    has_gpu: bool = False
    has_temp_sensor: bool = False
    has_power_sensor: bool = False   # 仅信息字段，由 power_monitor 自行决定是否使用
    platform_name: str = "unknown"
    notes: Dict[str, str] = field(default_factory=dict)

@dataclass
class RawMetrics:
    ts_ms: int
    cpu_percent: float
    mem_used_mb: float
    mem_total_mb: float
    gpu_percent: Optional[float]
    gpu_mem_used_mb: Optional[float]
    temperature_c: Optional[float]
    probe_name: str
    status: ReadStatus
    latency_ms: float
    error_message: Optional[str] = None
    # 注意：power_watt 字段不在 RawMetrics 中，由 power_monitor 通过 PowerSample/PowerStatsFrame 旁路输出。

class PlatformProbe:
    name: str
    def is_available(self) -> bool: ...
    def detect_caps(self) -> PlatformCaps: ...
    def read_metrics(self) -> RawMetrics: ...
    def close(self) -> None: ...

class PlatformSampler:
    """非忙等定时采样器：time.monotonic + sleep，drift-free。"""
    def __init__(self, probe: PlatformProbe, interval_ms: int = 1000,
                 on_sample=None) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def poll_once(self) -> RawMetrics: ...
```

## 4.1 探测链与配置项
- `select_default_probe(prefer=("procfs", "psutil"))`：按优先级返回首个 `is_available()=True` 的探针；全部不可用时降级到 `DummyProbe` 并打 WARNING。
- 配置项前缀建议 `platform.*`：
  - `platform.sample_interval_ms`：默认 1000；
  - `platform.probe_priority`：默认 `["procfs", "psutil"]`，可显式指定 `["dummy"]` 用于 CI；
  - `platform.disable_metrics`：可选关闭某些字段（如 `["temperature_c"]`），用于无传感器场景；
  - `platform.read_timeout_ms`：保留字段，当前实现为非阻塞读，主要影响未来子进程类 backend。

## 5. 与其他模块交互
- `metrics_collector` 通过 `PlatformAdapter`/`PlatformSampler` 获取原始数据（不含功耗）。
- `power_monitor` 不依赖本模块，独立采集功耗并输出统计快照。
- `runtime_guardian` 可读取能力信息用于降级决策。

## 6. 测试策略要点
- 不同设备/模拟环境能力探测测试。
- 传感器缺失场景测试（应返回 None 而非崩溃）。
- 高并发调用稳定性与耗时基准测试。
- 回归测试需确认：本模块的任何路径都不再产出功耗读数（`RawMetrics` 不含 `power_watt`，`read_metrics()` 不应触发 `sysfs/power_supply`、`tegrastats`、`jtop` 调用）。
- **基线开销测试**：`tests/platform_adapter/test_baseline.py`，DummyProbe 30s @100ms 空跑，PASS 阈值 CPU 时间增量 < 5ms、RSS 增量 < 5MB。当前实测 0.00ms / 0.04MB（开发机）。
- **集成测试**：`integration/test_adapter_to_collector.py`，10s @1Hz 真实探针 → MockMetricsCollector 校验 `RawMetrics` 字段集 + `MetricSnapshot.power_watt is None`。当前实测 12 帧 / 0 字段违规（开发机降级到 DummyProbe）。
