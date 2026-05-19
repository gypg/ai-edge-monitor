# 变更说明：platform_adapter 模块骨架落地

- 状态：已生效
- 日期：2026-05-19
- 涉及 PRD：`docs/prd/platform_adapter.md`、`docs/prd/README.md`
- 涉及代码：`src/platform_adapter/`、`tests/platform_adapter/`、`integration/test_adapter_to_collector.py`

## 1. 变动摘要

承接 [add-power-monitor](./add-power-monitor.md) 的模块拆分，正式落地 `platform_adapter` 的代码骨架与 PRD 第二轮细化：

- 新模块 `src/platform_adapter/`：
  - `probe.py`：`PlatformProbe` 抽象基类、`PlatformCaps`、`RawMetrics`、`DummyProbe`。
  - `procfs_probe.py`：`ProcfsProbe`，纯 stdlib 读取 `/proc/stat`（CPU 增量法）、`/proc/meminfo`、`/sys/class/thermal`。
  - `psutil_probe.py`：`PsutilProbe`，跨平台回退（psutil 可选依赖）。
  - `sampler.py`：`PlatformSampler`，复用 `power_monitor` 同款 `time.monotonic + sleep` 非忙等定时模式。
  - `__init__.py`：导出公共 API + `select_default_probe(prefer)` 探测链工厂。
- 测试：
  - `tests/platform_adapter/test_baseline.py`：DummyProbe 30s @100ms 空跑基线，PASS 阈值 CPU < 5ms、RSS < 5MB。
  - `integration/test_adapter_to_collector.py`：10s @1Hz 探针 → `MockMetricsCollector`，校验 `RawMetrics` 字段集 + `MetricSnapshot.power_watt is None`。

## 2. 关键设计决策

1. **三段式探测链 procfs → psutil → dummy**
   - procfs 优先：避免 psutil 依赖在最小镜像中缺失，CPU/内存读取也更可控（增量法直接用 `/proc/stat`）。
   - psutil 作回退：用于无 procfs 的开发机（Windows / macOS）和需要更丰富温度传感器的 Linux 主机。
   - DummyProbe 兜底：CI / 离线环境保证集成链路始终可跑。

2. **职责严格隔离功耗**
   - `RawMetrics` 字段中故意没有 `power_watt`。MockMetricsCollector 在 `collect_from_raw()` 里会显式断言这一点，把"adapter 又开始读功耗"作为契约违规处理。
   - `PlatformCaps.has_power_sensor` 保留为信息字段，仅供 `power_monitor` 探测时参考，不被本模块自身消费。

3. **CPU 增量算法选择**
   - `/proc/stat` 走"两次读取取差"的标准做法：`(1 - Δidle/Δtotal) * 100`。第一次调用没有基线，返回 0%；这与 psutil `cpu_percent(interval=None)` 行为一致，调用方需要"丢掉首样"或忽略首帧。
   - psutil 路径在 `PsutilProbe.__init__` 里预热一次 `cpu_percent`，避免首样为 0 给上层造成困惑——两条路径策略不同是有意的：procfs 让调用方决定如何处理首样，psutil 自带预热。

4. **基线开销与 power_monitor 对齐**
   - 复用了 `tests/power_monitor/test_baseline.py` 的同款 CPU/RSS 测量框架（baseline 减去 sleep-only loop、psutil → tasklist → /proc/self/status 三段 RSS fallback）。两个模块共用一组阈值，避免后续 CI 一边松一边紧。

## 3. 实测结果（开发机 Windows + Python 3.11）

| 测试 | 阈值 | 实测 | 结论 |
|---|---|---|---|
| `tests/platform_adapter/test_baseline.py` | CPU 时间增量 < 5ms / RSS 增量 < 5MB | 0.00ms / 0.04MB | PASS |
| `integration/test_adapter_to_collector.py` | ≥ 9 帧 + 0 字段违规 | 12 帧 / 0 违规 | PASS |
| `integration/test_power_to_analyzer.py`（回归） | ≥ 9 帧 + 0 字段违规 | 12 帧 / 0 违规 | PASS（未受影响） |

开发机上 procfs 与 psutil 均不可用（Windows + 无 psutil），按预期降级到 `DummyProbe` 并打 WARNING。

## 4. 影响范围

### 4.1 PRD 文档
| 文件 | 变更点 |
|---|---|
| `docs/prd/platform_adapter.md` | 新增 v3 段落，列出已落地骨架；扩展 `RawMetrics`（`ts_ms / probe_name / status / latency_ms / error_message`）；新增 `PlatformSampler` 接口；新增 `platform.*` 配置项；测试策略加入基线 + 集成实测数据 |
| `docs/prd/README.md` | 文档索引补充本变更说明 |

### 4.2 代码
- 新增上文列出的 5 个源文件 + 2 个测试 / 集成脚本。
- 待办（本次未做）：
  - `metrics_collector` 实现层接入 `PlatformSampler`，把 `RawMetrics → MetricSnapshot` 的 `sanitize` 路径补齐；
  - GPU/Jetson 专用 probe（`JetsonProbe` / `NvmlProbe`）；
  - 与 `runtime_guardian` 联动的降级通道（关闭部分字段、降低采样率）；
  - `config_manager` 落实 `platform.*` 配置项的加载与校验。

### 4.3 与 power_monitor 的接口冲突
- 本轮开发未引入新的接口冲突。
- 上一轮已修复的 `PowerStatsFrame` 契约（`window_start_ms`、`fail_rate`、`source_name`、`quality` 等）继续保留并通过回归测试。

## 5. 集成测试影响

1. CI 应同时跑 `tests/power_monitor/test_baseline.py` 与 `tests/platform_adapter/test_baseline.py`，作为两个模块的快速烟雾测试。
2. CI 应同时跑两个 `integration/test_*.py`，确保两条独立旁路（CPU/内存指标主链路 + 功耗旁路）都不破契约。
3. 当未来 `metrics_collector` 真正实现时，`integration/test_adapter_to_collector.py` 中的 `MockMetricsCollector` 应替换为真实模块；当前的字段校验逻辑可以直接保留作为回归检查点。
4. 真机验收需要补充：在 Jetson Nano / 树莓派 4B / x86 边缘服务器上各跑一次 baseline + integration，记录 procfs 路径下 CPU 利用率读数是否单调合理（首样 0% 是预期）。

## 6. 回滚策略

- 整个 `src/platform_adapter/` 与对应测试可独立删除，不影响 `power_monitor`。
- `docs/prd/platform_adapter.md` 中删除 v3 段落即可恢复到 add-power-monitor 时的版本。
