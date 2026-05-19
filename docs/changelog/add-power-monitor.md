# 变更说明：新增 power_monitor 模块（功耗采集职责剥离）

- 状态：已生效
- 日期：2026-05-19
- 涉及 PRD：`docs/prd/README.md`、`docs/prd/platform_adapter.md`、`docs/prd/aggregator_analyzer.md`、`docs/prd/power_monitor_detailed.md`
- 涉及代码：`src/power_monitor/`、`tests/power_monitor/`

## 1. 变动摘要

将“板级功耗采集与窗口统计”这一职责从 `platform_adapter` / `metrics_collector` 主链路中剥离，新增独立模块 `power_monitor`：

- 平台层不再读取 `power_now` / `current_now` / `voltage_now`，也不再调用 `tegrastats` / `jtop` 获取功耗轨道。
- 新模块 `power_monitor` 拥有自己的源抽象 `PowerSource`、采样器 `PowerSampler`（基于 `time.monotonic()` 的非忙等定时）、统计器 `PowerStats`，并对外输出 `PowerSample` 与 `PowerStatsFrame`。
- 数据流从 “platform_adapter → metrics_collector → aggregator_analyzer” 单线，调整为：通用指标走原链路；功耗作为旁路，由 `power_monitor` 直接将 `PowerStatsFrame` 推给 `aggregator_analyzer` 做联合分析，并由 `storage_exporter` 单独落盘。

## 2. 变动原因

1. **职责分离**：功耗采集的硬件耦合度（sysfs 节点差异、jtop 库依赖、tegrastats 子进程生命周期）显著高于其他指标，混在通用适配层中拖累其可移植性与可测性。
2. **故障隔离**：功耗源易出现 IO 错误、解析失败、子进程异常退出。独立模块可在内部完成回退/熔断/降级，不让功耗故障污染主采样循环。
3. **频率独立**：功耗默认 1Hz、可降到 0.2Hz；CPU/内存常用 1~2Hz。耦合在一起会让任一边的频率调整波及对方。
4. **开销可量化**：独立模块更易做基线测试。已实现 `tests/power_monitor/test_baseline.py`，DummySource 30s @100ms 实测 CPU 增量 < 1ms、RSS 增量 < 0.1MB，远低于 PRD 6.1 节阈值（<5ms / <5MB）。

## 3. 影响范围

### 3.1 PRD 文档
| 文件 | 变更点 |
|---|---|
| `docs/prd/README.md` | 模块数 9→10；依赖图与数据流图新增 power_monitor 旁路；`MetricSnapshot.power_watt` 标注为旁路字段；新增 `PowerStatsFrame` 跨模块结构 |
| `docs/prd/platform_adapter.md` | 删除功耗读取相关功能需求与 backend；`RawMetrics` 移除 `power_watt`；`PlatformCaps.has_power_sensor` 降级为信息字段；新增回归测试要求 |
| `docs/prd/aggregator_analyzer.md` | 输入接口新增 `ingest_power_stats(PowerStatsFrame)`；`AnalysisFrame` 扩展 `p95_power_watt` / `energy_joule` / `power_quality` / `power_source_name`；测试要点新增跨源对齐用例 |
| `docs/prd/power_monitor_detailed.md` | 已存在，本次未改 |

### 3.2 代码
- 新增：`src/power_monitor/{__init__,source,sampler,stats}.py`，`tests/power_monitor/test_baseline.py`。
- 待办（本次未做，不阻塞）：
  - `platform_adapter` 实现层删除功耗 backend 与 `RawMetrics.power_watt` 字段；
  - `metrics_collector` 取消对 `RawMetrics.power_watt` 的依赖；
  - `aggregator_analyzer` 实现 `ingest_power_stats` 与 `AnalysisFrame` 新字段；
  - `storage_exporter` 增加 `PowerSample` / `PowerStatsFrame` 落盘通道；
  - `app_orchestrator` 在装配阶段实例化并启动 `PowerMonitorService`；
  - `runtime_guardian` 增加面向 `power_monitor.apply_degrade()` 的下行通道。

### 3.3 配置
配置项前缀 `power.*`（详见 `power_monitor_detailed.md` §9）。已有的 `metrics.power.*` 类配置（如有）应迁移至 `power.*`，并在 `config_manager` 加上一次性兼容映射。

## 4. 对集成测试的潜在影响

1. **回归项**：原本会断言 `RawMetrics.power_watt` 非空的用例必须改写。任何落盘文件的 schema 校验若把功耗字段绑死在主指标 CSV/JSONL 上，需要拆分到独立的 `power_*.jsonl`，或改为可空。
2. **接收方对齐**：`aggregator_analyzer` 的窗口统计现在依赖跨源时间戳对齐。新增对齐测试需覆盖：
   - `MetricSnapshot` 与 `PowerStatsFrame` 的时间戳错位（功耗帧延迟、丢帧）；
   - `quality ∈ {estimated, unavailable}` 时 `AnalysisFrame.avg_power_watt` 是否被排除出瓶颈判定；
   - `power_monitor` 全部源不可用时，主分析链路是否仍能正常输出。
3. **三平台验收**：`docs/prd/power_monitor_detailed.md` §14 已规定 Jetson Nano / 树莓派 4B / x86 边缘服务器的独立验收脚本（12 分钟，PASS/FAIL）。集成测试 CI 应将其作为 `power_monitor` 的门禁，独立于 `platform_adapter` 的能力探测用例。
4. **基准开销门禁**：`tests/power_monitor/test_baseline.py` 已落地（DummySource 30s @100ms，PASS）。建议把它接入 CI 作为快速烟雾测试，避免后续平台源实现破坏“<5ms / <5MB”指标。
5. **运行守护联动**：`runtime_guardian` 的降级路径过去只会调用通用调度器；现在需要新增对 `power_monitor` 的降级触达，集成测试要验证两边的降级互不阻塞、恢复后能各自独立升频。

## 5. 回滚策略

如需短期回滚（例如新模块在某平台不稳）：
- 保留 `power_monitor` 代码与 PRD，仅在 `app_orchestrator` 装配阶段不启动它；
- `aggregator_analyzer.ingest_power_stats` 对空输入应天然降级（输出 `avg_power_watt=None`）；
- `platform_adapter` 不要回滚到“双方都采集”的状态——在重复采集场景下 sysfs / jtop 的句柄竞争是已知风险，回滚到旧版会再次触发。
