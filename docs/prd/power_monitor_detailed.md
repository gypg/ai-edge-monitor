# power_monitor 模块详细 PRD

## 1. 模块目标与定位

`power_monitor` 是独立的“功耗采集与统计算模块”，职责是：
1. 以**最低开销**稳定采集设备功耗相关指标；
2. 在模块内部完成功耗窗口统计与能量估算；
3. 向上游输出标准化功耗快照与统计结果，供全局分析与可视化复用。

该模块不负责全局 CPU/GPU/内存指标采集，只聚焦功耗链路，避免职责混杂。

---

## 2. 模块边界与上下游关系

### 2.1 输入
- `config_manager` 提供功耗采样参数（频率、启用源、超时、降级阈值）。
- `runtime_guardian` 可下发降级/恢复指令（例如降低采样频率）。

### 2.2 输出
- `PowerSample`：单次功耗采样结果。
- `PowerStatsFrame`：窗口统计结果（avg/max/p95、能量估计等）。
- `PowerHealth`：采样健康状态（失败率、抖动、源可用性）。

### 2.3 交互
- 上行给 `aggregator_analyzer`：用于跨指标联合分析。
- 上行给 `storage_exporter`：落盘原始样本和统计帧。
- 上行给 `visualization`：绘制功耗曲线、能量柱状图。

---

## 3. 抽象层设计（平台相关实现）

采用双层抽象：

1. **PowerSource（平台采集源层）**
   - 专注“如何从当前平台读取功耗值”。
   - 屏蔽 psutil / jetson-stats / tegrastats / sysfs 差异。

2. **PowerSampler + PowerStats（采样与统计层）**
   - 专注“何时采、怎么低开销采、怎么统计”。
   - 与具体平台无关，仅消费统一 `PowerReading`。

### 3.1 类图（概念）

```text
PowerSource (Protocol)
  ├─ SysfsPowerSource
  ├─ JetsonStatsPowerSource
  ├─ TegrastatsPowerSource
  └─ NullPowerSource

PowerSourceManager
  └─ 负责探测、优先级选择、故障切换

PowerSampler
  └─ 周期调度 + 低开销睡眠 + 抖动统计

PowerStats
  └─ 滑窗统计 + 能量积分

PowerMonitorService
  └─ 模块统一入口（start/stop/read_latest/get_stats）
```

---

## 4. 数据源兼容策略（必须项）

> 原则：**优先兼容性，其次精度，再次实现复杂度**。默认“能跑起来”优先。

### 4.1 数据源优先级

1. `/sys/class/power_supply`（Linux sysfs，首选）
2. `jetson-stats`（Jetson 生态，Python 友好）
3. `tegrastats`（Jetson 原生命令，作为后备）
4. `psutil`（仅用于进程/系统功耗代理指标，不作为真实板级功耗主来源）

### 4.2 各源使用策略

#### A) `/sys/class/power_supply`（首选）
- 读取路径示例：
  - `.../power_now`（通常微瓦 uW）
  - `.../current_now` + `.../voltage_now`（推导功率）
- 策略：
  - 启动时扫描 `type=Mains/Battery/USB` 与可读字段。
  - 优先直接文件读取，避免子进程。
  - 单位统一转为 `W`。
- 兼容优势：依赖最小，跨多数 Linux 设备可工作。

#### B) `jetson-stats`（Jetson 推荐）
- 使用 `jtop` API 获取功耗轨信息（如 VDD_IN）。
- 策略：
  - 检测库是否安装且设备支持。
  - 若可用，作为 Jetson 场景高优先源（可获取更语义化轨道功耗）。
- 兼容策略：不可用时自动回退 sysfs 或 tegrastats。

#### C) `tegrastats`（Jetson 后备）
- 以低频子进程模式读取（例如 1000ms 输出间隔）。
- 策略：
  - 仅在 `jetson-stats` 不可用且 sysfs 信息不足时启用。
  - 使用长生命周期单进程 + 流式解析，禁止每次采样启动新进程。
- 风险控制：子进程解析失败时熔断并回退。

#### D) `psutil`（辅助）
- `psutil` 本身不直接给板级功耗。
- 使用策略：
  - 仅用于记录监控进程自身 CPU 时间与内存开销（用于开销评估）。
  - 可选用于功耗估计模型输入（如 CPU 利用率代理），需打 `estimated=true` 标记。

### 4.4 三类设备完整数据获取链路与耗时评估

| 设备类型 | 主链路（优先） | 回退链路 | 调用到取值完整路径 | 单次采集耗时（大致范围） |
|---|---|---|---|---|
| Jetson Nano | `jetson-stats (jtop)` 或 `sysfs` | `tegrastats` -> `estimated/None` | `PowerSampler.next_sample()` -> `PowerSourceManager.read_with_fallback()` -> `JetsonStatsPowerSource.read_once()`（内部调用 jtop API 读取 VDD_IN）-> 单位标准化 -> `PowerReading` | jtop: **2~8ms**；sysfs: **0.2~3ms**；tegrastats 流式解析: **3~12ms** |
| 树莓派 4B | `sysfs`（若存在 power/current/voltage 节点） | `estimated/None` | `PowerSampler.next_sample()` -> `PowerSourceManager.read_with_fallback()` -> `SysfsPowerSource.read_once()`（读取 `power_now` 或 `current_now*voltage_now`）-> 单位标准化 -> `PowerReading` | sysfs: **0.2~4ms**（取决于内核导出节点与I/O状态） |
| 通用 x86 边缘服务器 | `sysfs`（电池/电源传感器存在时） | `estimated/None` | `PowerSampler.next_sample()` -> `PowerSourceManager.read_with_fallback()` -> `SysfsPowerSource.read_once()` -> 单位标准化 -> `PowerReading` | sysfs: **0.1~3ms**；无传感器时快速失败: **<1ms** |

说明：
- 表中耗时是“单次 read_once 的 CPU 时间 + 少量解析”，不包含窗口统计与落盘。
- `tegrastats` 若采用“每次采样启动子进程”，耗时会飙升到几十毫秒甚至更高，本模块明确禁止该模式。
- 树莓派 4B 上是否能拿到“真实板级功耗”取决于硬件/驱动暴露；若无对应传感器，必须返回 `quality=unavailable` 或 `estimated`，不得伪装成实测值。

---

## 5. 功能需求（必须完成）

1. **能力探测与源选择**
   - 启动阶段探测可用数据源并确定主源与备源。

2. **周期采样**
   - 以配置频率采集 `power_watt`、`voltage_v`、`current_a`（能取则取）。

3. **单位标准化**
   - 所有输出统一单位：功率 `W`、电压 `V`、电流 `A`。

4. **窗口统计**
   - 计算 `avg/max/min/p95`，并输出窗口能量 `energy_joule`。

5. **健康与质量标注**
   - 每条样本标注 `source_name`、`quality`（raw/derived/estimated）。
   - 输出失败率、采样抖动、回退次数。

6. **降级与恢复**
   - 当采样超时/开销超阈值时自动降频或切换源。
   - 条件恢复后可自动升频（带冷却时间）。

---

## 6. 非功能需求（量化指标）

### 6.1 性能与资源
- 单次采集 CPU 时间增量（`PowerSource.read_once` 纯采集路径）：
  - **sysfs 直读路径**：P95 **< 5ms**（目标），P99 < 8ms；
  - **jetson-stats 路径**：P95 **< 8ms**（目标）；
  - **tegrastats 流式解析路径**：P95 **< 12ms**（目标，不含进程启动，因为要求常驻单进程）。
- 常驻内存增量：**< 5MB**（模块独占，稳定运行后）。
- 默认采样频率（1Hz）下模块 CPU 占比：**< 2%**（单核等效，P95）。
- 采样线程抖动：**P95 < 采样间隔的 10%**。

> 评审修正：原“单次采集 CPU 时间增量 <5ms”作为统一硬指标过于激进，现按数据源分层约束。对于树莓派 4B/Jetson 这类设备，`open+read+parse` sysfs 文本在缓存命中场景通常可落入毫秒级，<5ms 在 1Hz 场景是可实现目标；但若通过高层库间接调用或引入子进程，抖动会显著上升，因此必须坚持“sysfs 直读优先、禁止每次采样拉起子进程”。

> 实现建议：无需改为 C 扩展或更低级语言。优先做 Python 侧低开销实现（预解析路径、复用 fd/缓冲、减少字符串分配、避免 subprocess）。仅在实测不达标时再考虑 Cython/Rust 扩展。

### 6.2 可靠性
- 连续运行 24h 无崩溃。
- 数据源短时失败可自恢复，失败期间主流程不中断。
- 错误路径不抛出未捕获异常到顶层。

### 6.3 可移植性
- Linux ARM64/x86_64 必须支持。
- Jetson 专项增强（jetson-stats/tegrastats）为可选能力，不可作为硬依赖。

---

## 7. 低开销采样频率与定时策略

## 7.1 频率分层
- 默认频率：`1Hz`（`sample_interval_ms=1000`）。
- 可选高频：`2Hz`（500ms，仅压测/短时诊断）。
- 降级频率：`0.5Hz` 或 `0.2Hz`（2s/5s）。

### 7.2 定时机制（避免忙等待）
- 使用 `time.monotonic()` 计算下一触发时刻：`next_t += interval`。
- 使用 `sleep(max(0, next_t-now))` 阻塞等待。
- 严禁 while 自旋检查（busy wait）。
- 超期补偿：若采样耗时过长，仅跳过过期节拍，不追帧补采。
- 建议在独立采样线程执行 `next_sample()`，并将结果通过无界面阻塞队列交给后续处理，避免被主线程其他任务拖慢。

### 7.3 Python GIL 与定时精度风险（评审补充）
- 风险：当同进程存在 CPU 密集 Python 线程时，GIL 竞争可能放大调度抖动，导致 `sleep` 唤醒后无法立即执行采样。
- 约束：
  - 采样路径必须保持短临界区（读取+解析后立即释放控制权）；
  - 禁止在采样线程内做统计重计算或I/O落盘；
  - 与推理任务同进程部署时，建议将监控器以独立进程运行（首选），降低 GIL 相互影响。
- 验证指标：在目标设备上实测 `jitter_p95`、`missed_tick_rate`，超阈值时由 `runtime_guardian` 触发降频。

---

## 8. 接口定义（Python 伪代码草案）

```python
from dataclasses import dataclass
from typing import Optional, Protocol, Literal

Quality = Literal["raw", "derived", "estimated", "unavailable"]
ReadStatus = Literal["ok", "timeout", "io_error", "parse_error", "not_supported"]

class PowerMonitorError(Exception): ...
class PowerSourceInitError(PowerMonitorError): ...

@dataclass(slots=True)
class PowerConfig:
    sample_interval_ms: int = 1000
    window_size: int = 60
    source_priority: tuple[str, ...] = ("sysfs", "jtop", "tegrastats")
    read_timeout_ms: int = 50
    enable_estimation: bool = False
    degrade_intervals_ms: tuple[int, ...] = (2000, 5000)
    fail_rate_threshold: float = 0.2
    max_consecutive_timeout: int = 3

@dataclass(slots=True)
class PowerReading:
    ts_ms: int
    power_watt: Optional[float]
    voltage_v: Optional[float]
    current_a: Optional[float]
    source_name: str
    quality: Quality
    status: ReadStatus
    latency_ms: float
    error_message: Optional[str] = None

@dataclass(slots=True)
class PowerSample:
    reading: PowerReading
    seq: int

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

class PowerSource(Protocol):
    name: str
    def is_available(self) -> bool: ...
    def read_once(self, timeout_ms: int) -> PowerReading: ...
    def close(self) -> None: ...

class PowerSourceManager:
    def __init__(self, config: PowerConfig, sources: list[PowerSource]): ...
    def select_primary(self) -> PowerSource: ...
    def read_with_fallback(self, timeout_ms: int) -> PowerReading: ...
    def health(self) -> dict: ...

class PowerStats:
    def __init__(self, window_size: int): ...
    def ingest(self, sample: PowerSample) -> None: ...
    def flush(self) -> Optional[PowerStatsFrame]: ...

class PowerSampler:
    def __init__(self, cfg: PowerConfig, source_manager: PowerSourceManager): ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def set_interval_ms(self, interval_ms: int) -> None: ...
    def next_sample(self) -> PowerSample: ...

class PowerMonitorService:
    def __init__(self, cfg: PowerConfig): ...
    def start(self) -> None: ...
    def poll(self) -> PowerSample: ...
    def maybe_emit_stats(self) -> Optional[PowerStatsFrame]: ...
    def apply_degrade(self, reason: str) -> None: ...
    def recover(self) -> None: ...
    def shutdown(self) -> None: ...
```

### 8.1 异常处理约定（评审后补充）
- `PowerSource.read_once()`：**不向上抛读取类异常**（IO/解析/超时），统一返回 `PowerReading(status!=ok, power_watt=None, error_message=...)`。
- `PowerSource.__init__` / `PowerMonitorService.start()`：初始化阶段若关键资源不可用，可抛 `PowerSourceInitError`，由 orchestrator 决定降级或禁用模块。
- `PowerSourceManager.read_with_fallback()`：尝试主源失败后按优先级回退，若全部失败返回 `status=not_supported` 或 `status=io_error` 的 `PowerReading`，不抛异常中断主采样循环。
- `PowerStats.ingest()`：对 `quality=unavailable` 样本仅计入失败率，不参与能量积分。


---

## 9. 配置项定义（建议落地到 config_manager）

- `power.enabled: bool`
- `power.sample_interval_ms: int`（默认 1000）
- `power.window_size: int`（默认 60）
- `power.source_priority: [sysfs, jtop, tegrastats]`
- `power.read_timeout_ms: int`（默认 50）
- `power.enable_estimation: bool`（默认 false）
- `power.degrade_intervals_ms: [2000, 5000]`
- `power.fail_rate_threshold: float`（默认 0.2）
- `power.max_consecutive_timeout: int`（默认 3）

---

## 10. 与其他模块交互方式

1. `app_orchestrator` 启动 `PowerMonitorService` 生命周期。
2. `sampler_scheduler` 可选两种模式：
   - 外部调度模式：由总调度器调用 `poll()`；
   - 内部调度模式：`PowerSampler` 自主定时（推荐功耗独立低频场景）。
3. `aggregator_analyzer` 消费 `PowerStatsFrame`，做跨资源关联分析。
4. `storage_exporter` 分别落盘 `PowerSample` 与 `PowerStatsFrame`。
5. `runtime_guardian` 根据监控器自身开销触发 `apply_degrade()`。

---

## 11. 错误处理与自恢复策略

- 数据源读取超时：记录错误并走 fallback，不中断主循环。
- 连续读取失败：进入 degraded 模式，降低频率并打点。
- 源级熔断：短时间内失败过多，暂时禁用该源，冷却后再探测。
- 关闭流程：确保子进程源（如 tegrastats）被正确回收。

---

## 12. 测试策略要点

### 12.1 单元测试
- 各 `PowerSource` 的单位转换正确性。
- fallback 选择逻辑正确性。
- `PowerStats` 的 p95/能量积分计算正确性。

### 12.2 集成测试
- Jetson 环境：jtop/tegrastats 链路验证。
- 通用 Linux：sysfs 链路验证。
- 源缺失场景：返回 `None/estimated` 的行为验证。

### 12.3 性能基准测试
- 采样 1Hz/2Hz 下单次采集耗时分布。
- 长跑 1h 内内存增量与 GC 次数。
- 采样抖动与失败率统计。

### 12.4 故障注入测试
- 模拟读取文件权限错误、命令超时、子进程异常退出。
- 验证降级、熔断、恢复路径均可达且不崩溃。

---

## 13. 风险与落地建议

1. **不同设备功耗字段语义不一致**
   建议在样本中保留 `source_name` 与原始字段映射版本号，避免误解读。

2. **tegrastats 文本解析脆弱**
   建议将解析器独立并用真实样本回放测试覆盖。

3. **估算功耗易被误用为真实值**
   建议强制 `quality=estimated` 并在可视化层显式标注虚线/灰色。

4. **低端设备上 Python 定时抖动偏大**
   建议默认 1Hz 并允许 `runtime_guardian` 动态降频。

---

## 14. 验收基准与测试设计

本节定义 `power_monitor` 在 Jetson Nano、树莓派 4B、x86 边缘服务器上的自动化验收流程与 PASS/FAIL 判定标准。

### 14.1 验收前提与统一测试条件

- 测试时长：**至少 10 分钟**（建议 12 分钟，其中前 2 分钟 warm-up，后 10 分钟计入统计）。
- 采样间隔：默认 **1000ms（1Hz）**；可选补充 **500ms（2Hz）** 压测。
- 运行模式：
  - 模式 A（推荐）：监控器独立进程运行；
  - 模式 B（可选）：与业务进程同机并行，验证干扰。
- 落盘要求：输出原始 `PowerSample` 和窗口 `PowerStatsFrame`（JSONL/CSV 均可）。
- 计时基准：使用 `time.monotonic()` 记录 tick 间隔与抖动。

### 14.2 三平台自动化验收步骤

#### A) Jetson Nano

1. 环境检查：
   - 检测 `python`、`psutil` 可用；
   - 探测 `jetson-stats(jtop)` 是否可用；
   - 探测 `/sys/class/power_supply` 节点；
   - 若前两者不可用，探测 `tegrastats`。
2. 链路选择：按 `sysfs/jtop/tegrastats` 优先级选主源，记录 `selected_source`。
3. 执行采样：持续运行 12 分钟（2 分钟 warm-up + 10 分钟验收）。
4. 统计输出：计算采样延迟、抖动、失败率、回退次数、内存增量、CPU 时间增量。
5. 自动判定：按 14.3 阈值生成 `PASS/FAIL` 与失败原因列表。

#### B) 树莓派 4B

1. 环境检查：
   - 检测 `python`、`psutil`；
   - 探测 `/sys/class/power_supply` 是否存在有效 `power_now` 或 `current_now+voltage_now`。
2. 链路选择：优先 `sysfs`；若无真实功耗节点，进入 `estimated/None` 路径并标记 `quality`。
3. 执行采样：持续运行 12 分钟（同上）。
4. 统计输出：同 Jetson，额外统计 `unavailable_ratio`。
5. 自动判定：
   - 若设备无真实功耗硬件暴露，允许“功能降级通过”（质量标记正确 + 稳定性达标）；
   - 若有真实节点，则按完整性能阈值判定。

#### C) x86 边缘服务器

1. 环境检查：
   - 检测 `python`、`psutil`；
   - 探测 `/sys/class/power_supply` 或其他可读电源节点。
2. 链路选择：`sysfs` 优先；无节点则 `estimated/None`。
3. 执行采样：持续运行 12 分钟（同上）。
4. 统计输出：同上。
5. 自动判定：按 14.3 阈值；无真实传感器时按“降级通过”规则。

### 14.3 量化验收阈值（PASS/FAIL 标准）

#### 14.3.1 性能阈值

在“后 10 分钟有效窗口”内判定：

- 单次采集 CPU 时间增量（`read_once` 路径）
  - sysfs: `latency_ms_p95 < 5ms`，`latency_ms_p99 < 8ms`
  - jtop: `latency_ms_p95 < 8ms`
  - tegrastats(常驻流式): `latency_ms_p95 < 12ms`
- 采样线程抖动：`jitter_p95 < interval_ms * 10%`
- 监控模块 CPU 占比：`monitor_cpu_pct_p95 < 2.0`
- 常驻内存增量：`rss_delta_mb <= 5.0`

#### 14.3.2 稳定性阈值

- 有效样本数：`samples_collected >= 600`（1Hz、10分钟）
- 失败率：`fail_rate <= 1.0%`（真实源场景）
- 回退后稳定：fallback 发生后 30 秒内恢复稳定采样（无连续失败）
- 无崩溃：进程退出码为 0，且无未捕获异常

#### 14.3.3 兼容性/降级阈值

- 当无真实功耗源时，必须满足：
  - `quality` 字段准确为 `unavailable` 或 `estimated`；
  - 不得输出伪造 `raw` 功耗值；
  - 采样循环稳定（失败率可放宽到 `<= 5%`，但不得中断主循环）。

### 14.4 “内存增量 < 5MB”验证方法

- 基线：启动采样前读取一次 `rss_mb_baseline`（通过 `psutil.Process().memory_info().rss`）。
- 观测：采样过程中每 5 秒记录 `rss_mb_current`。
- 结果：使用稳定阶段（最后 5 分钟）`rss_mb_p95 - rss_mb_baseline` 作为 `rss_delta_mb`。
- 判定：`rss_delta_mb <= 5.0` 为通过。

说明：避免用瞬时峰值做唯一标准，防止短期 GC 抖动误判；同时需报告 `rss_peak_delta_mb` 供诊断。

### 14.5 自动化验收脚本伪代码（PASS/FAIL）

```python
import time
import psutil
from statistics import quantiles


def p95(values):
    if not values:
        return None
    return quantiles(values, n=100)[94]


def run_acceptance(device_type: str, interval_ms: int = 1000, total_sec: int = 720):
    # total_sec=720 -> 12分钟（2分钟warm-up + 10分钟验收）
    warmup_sec = 120
    eval_sec = 600

    monitor = PowerMonitorService(load_power_config(device_type, interval_ms))
    proc = psutil.Process()

    rss_baseline = proc.memory_info().rss / (1024 * 1024)
    cpu_time_baseline = sum(proc.cpu_times()[:2])  # user + system

    monitor.start()

    latencies = []
    jitters = []
    fail_count = 0
    fallback_count = 0
    quality_bad_count = 0

    last_tick = time.monotonic()
    eval_start = None

    for _ in range(int(total_sec * 1000 / interval_ms)):
        now = time.monotonic()
        sample = monitor.poll()  # 内部 read_once + fallback

        tick_interval = (now - last_tick) * 1000
        jitter = abs(tick_interval - interval_ms)
        jitters.append(jitter)
        last_tick = now

        # 进入评估窗口（跳过warm-up）
        if eval_start is None and (time.monotonic() - (last_tick - tick_interval / 1000)) >= warmup_sec:
            eval_start = time.monotonic()

        in_eval = eval_start is not None and (time.monotonic() - eval_start) <= eval_sec
        if in_eval:
            latencies.append(sample.reading.latency_ms)
            if sample.reading.status != "ok":
                fail_count += 1
            if sample.reading.quality == "raw" and sample.reading.power_watt is None:
                quality_bad_count += 1
            # 可从 monitor.health 或 stats 读取 fallback 次数
            fallback_count = monitor.maybe_emit_stats().fallback_count if monitor.maybe_emit_stats() else fallback_count

        time.sleep(max(0, interval_ms / 1000.0))

    monitor.shutdown()

    rss_end = proc.memory_info().rss / (1024 * 1024)
    cpu_time_end = sum(proc.cpu_times()[:2])

    rss_delta_mb = rss_end - rss_baseline
    cpu_time_delta = cpu_time_end - cpu_time_baseline
    sample_count = len(latencies)
    fail_rate = (fail_count / sample_count) if sample_count else 1.0

    result = evaluate_thresholds(
        device_type=device_type,
        latency_p95=p95(latencies),
        jitter_p95=p95(jitters),
        fail_rate=fail_rate,
        rss_delta_mb=rss_delta_mb,
        sample_count=sample_count,
        quality_bad_count=quality_bad_count,
    )

    if result["pass"]:
        print("PASS")
    else:
        print("FAIL")
        for reason in result["reasons"]:
            print(f"- {reason}")

    return result


def evaluate_thresholds(device_type, latency_p95, jitter_p95, fail_rate, rss_delta_mb, sample_count, quality_bad_count):
    reasons = []

    # 通用阈值
    if sample_count < 600:
        reasons.append("有效样本不足(<600)")
    if rss_delta_mb > 5.0:
        reasons.append("常驻内存增量超过5MB")
    if jitter_p95 is not None and jitter_p95 > 100:  # 1Hz时10%为100ms
        reasons.append("采样抖动P95超过阈值")
    if quality_bad_count > 0:
        reasons.append("quality标注与功耗值不一致")

    # 设备/链路阈值（示意：实际应按 selected_source 细分）
    if latency_p95 is None:
        reasons.append("缺少有效延迟数据")
    elif device_type == "jetson_nano" and latency_p95 > 8:
        reasons.append("Jetson延迟P95超阈值(>8ms)")
    elif device_type in ("rpi4b", "x86_edge") and latency_p95 > 5:
        reasons.append("sysfs延迟P95超阈值(>5ms)")

    # fail_rate: 真实源场景<=1%，降级场景可按配置放宽
    if fail_rate > 0.01:
        reasons.append("失败率超过1%")

    return {
        "pass": len(reasons) == 0,
        "reasons": reasons,
        "metrics": {
            "latency_p95_ms": latency_p95,
            "jitter_p95_ms": jitter_p95,
            "fail_rate": fail_rate,
            "rss_delta_mb": rss_delta_mb,
            "sample_count": sample_count,
        },
    }
```

### 14.6 验收输出格式（建议）

脚本输出 `acceptance_result.json`，至少包含：
- `device_type`
- `selected_source`
- `test_duration_sec`
- `interval_ms`
- `metrics`（latency/jitter/fail_rate/rss_delta/sample_count）
- `thresholds`
- `pass`（bool）
- `reasons`（失败原因数组）

建议在 CI/本地命令中统一为：
- `python tools/power_acceptance.py --device jetson_nano --interval-ms 1000 --duration-sec 720`

