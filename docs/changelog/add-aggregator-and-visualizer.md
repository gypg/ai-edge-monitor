# 变更说明：aggregator_analyzer + visualizer 骨架与端到端打通

- 状态：已生效
- 日期：2026-05-19
- 涉及 PRD：`docs/prd/aggregator_analyzer.md`、`docs/prd/visualization.md`、`docs/prd/README.md`
- 涉及代码：`src/aggregator_analyzer/`、`src/visualizer/`、`tests/aggregator_analyzer/`、`integration/test_e2e_collect_to_report.py`、`examples/generate_report.py`

## 1. 变动摘要

- 新增 `src/aggregator_analyzer/`：`AggregatorAnalyzer` 实现 `ingest_metrics(RawMetrics)` / `ingest_power_stats(PowerStatsFrame)` / `get_summary()` / `get_summary_dict()`，内部维护两个独立的时间窗口环形缓存（CPU/内存指标 + 功耗帧）。`WindowSummary` 同时携带聚合统计与短时间序列（`timeline_*` 字段），供 visualizer 直接绘制。
- 新增 `src/visualizer/`：`plot_report(data, output_path)` 双后端渲染——matplotlib 优先（CPU% + Power(W) 双 Y 轴 + 内存子图），不可用时回退到 stdlib `zlib`+手写 PNG chunk 的极简实现。两条路径都同时写一个 `<report>.png.json` sidecar，记录被绘制的原始 summary 和实际后端。
- 新增端到端集成测试 `integration/test_e2e_collect_to_report.py`：DummyProbe + DummySource 各 1Hz 采 10s → 双路 ingest → `get_summary_dict()` → `plot_report()` → PNG 头校验 + JSON sidecar 校验，输出单行 JSON 状态。
- 新增基线测试 `tests/aggregator_analyzer/test_baseline.py`：注入虚拟时钟，灌入 10000 帧后断言窗口剪裁正确、RSS 增量 < 5MB。
- 新增示例脚本 `examples/generate_report.py`：60 点合成数据 → `examples/sample_report.png`。
- CLI 入口：`python -m visualizer --input summary.json --output report.png`。

## 2. 关键设计决策

1. **不重算功耗滑窗**
   - `AggregatorAnalyzer` 直接使用 `PowerStatsFrame.{avg,p95,max,energy,fail_rate,quality,source_name}` 字段，不再从底层 `PowerSample` 重新做窗口聚合。
   - 原因：`power_monitor` 已完成单位标准化、失败率、质量传播；这里再做一次只会让两个模块的逻辑随时间漂移。功耗帧本身就是窗口摘要。
   - 副作用：`WindowSummary.power_avg_watt` 是"近 N 帧的 avg 之 mean"，`power_p95_watt` 取"近 N 帧的 p95 之 max"——这两个语义在 PRD 里写明，便于上层理解。

2. **两路独立 deque + 共享锁**
   - 一个源停摆（功耗源故障 / 探针卡顿）不会阻塞另一路。
   - `max_samples` 硬上限保证内存上界，即使时钟错乱也不会无限增长。

3. **可注入时钟**
   - `now: Callable[[], float]` 默认 `time.monotonic`，但测试可以驱动虚拟秒钟，让"60 秒窗口剪裁"在毫秒内验证完。基线测试就靠这个把 10000 帧塞进 60 秒窗口。

4. **WindowSummary 自带 timeline_***
   - 短序列直接挂在 summary 上，visualizer 无需第二次聚合。代价是 summary dict 体积稍大，但 100~600 个浮点数对 JSON sidecar 完全可控。

5. **Visualizer 双后端**
   - matplotlib 路径是给人看的——双 Y 轴、网格、文字摘要。
   - stdlib 路径是给 CI/边缘最小镜像用的——纯标准库（`zlib`+`struct`），保证流水线在任何 Python 3.8+ 环境都能产出合法 PNG。这次本机就走的 stdlib 路径，PNG 头校验通过。
   - JSON sidecar 是两条路径共享的"事实"：若图被裁了或后端不可用，reviewer 仍能从 sidecar 读出准确摘要。

## 3. 实测结果（开发机 Windows + Python 3.11，无 matplotlib / 无 psutil）

| 测试 | 阈值 / 期望 | 实测 | 结论 |
|---|---|---|---|
| `tests/aggregator_analyzer/test_baseline.py` | RSS 增量 < 5MB；窗口剪裁不溢出 | 0.11MB；retain 61/61 帧 | PASS |
| `integration/test_e2e_collect_to_report.py` | 报告 PNG 头有效；sidecar 含 timeline_*；样本 ≥ 9 | metrics=12, power=13, PNG=2383B, backend=stdlib | PASS |
| `integration/test_power_to_analyzer.py`（回归） | 0 字段违规 | 11 帧 / 0 违规 | PASS（未受影响） |
| `integration/test_adapter_to_collector.py`（回归） | 0 字段违规 | 11 帧 / 0 违规 | PASS（未受影响） |
| `examples/generate_report.py` | 生成 examples/sample_report.png | 写出 PNG + JSON sidecar | OK |

## 4. 影响范围

### 4.1 PRD 文档
| 文件 | 变更点 |
|---|---|
| `docs/prd/aggregator_analyzer.md` | 标注 v3：实现已落地；接口段补充 `WindowSummary` / `get_summary_dict()` / 时间序列字段；测试段补实测数据 |
| `docs/prd/visualization.md` | 标注 v2：实现已落地；明确 matplotlib 主路径 + stdlib PNG 回退、JSON sidecar 设计 |
| `docs/prd/README.md` | 文档索引补本变更说明 |

### 4.2 代码
- 新增：`src/aggregator_analyzer/{__init__,analyzer}.py`、`src/visualizer/{__init__,report,__main__}.py`、`tests/aggregator_analyzer/test_baseline.py`、`integration/test_e2e_collect_to_report.py`、`examples/generate_report.py`、生成产物 `examples/sample_report.png(+.json)` 与 `integration/test_report.png(+.json)`。
- 没有修改 `power_monitor` / `platform_adapter` 任何接口；两者的回归测试继续通过。
- 待办（本次未做）：
  - 在真实设备上验证 matplotlib 路径绘图正确性（开发机走的是 stdlib 回退）。
  - `metrics_collector` / `sampler_scheduler` 落地后，把 e2e 中的 "DummyProbe + DummySource" 替换成"真实采集器 + 真实功耗源"。
  - `storage_exporter` 与 `aggregator_analyzer` 的 push/pull 接口（当前只有 in-memory summary）。

## 5. 集成测试影响

- E2E 已成为流水线的最高级断言。CI 推荐顺序：基线 → 各模块 integration → e2e。
- 若引入新的下游消费者（storage 或可视化新视图），应优先扩展 `WindowSummary` 而非新增 ingest 路径，以维持"两路 ingest + 单一 summary"的简单契约。
- stdlib PNG 后端的存在，意味着 CI 不需要装 matplotlib 也能跑 e2e；但发布报告/给人看的环境仍应安装 matplotlib，否则回退图像没有坐标标签和文字摘要。

## 6. 回滚策略

- 删除 `src/aggregator_analyzer/`、`src/visualizer/`、`integration/test_e2e_collect_to_report.py`、`examples/generate_report.py`、`tests/aggregator_analyzer/`，并恢复 `docs/prd/aggregator_analyzer.md` / `docs/prd/visualization.md` 中本次新增的 v2/v3 段落即可。
- `power_monitor` / `platform_adapter` 不需要任何回滚动作。
