# 真实硬件验收报告

> 本报告分两部分：**A. 开发机冒烟测试**记录 2026-05-19 在 Windows 开发机上的实际 30 秒端到端运行结果；**B. 真实设备验收操作手册**给出在 Jetson Nano / 树莓派 4B / x86 边缘服务器上落地验收的可执行步骤与待填模板。

---

## A. 开发机冒烟测试（本次运行）

### A.1 环境

| 项 | 值 |
|---|---|
| 主机 | DESKTOP-QKUJBU2（Windows 开发工作站，**非边缘设备**） |
| OS | Windows 10 Pro 19045 |
| Shell | MSYS2 / MinGW bash（exposes 部分 `/proc` 给 shell，但 Python 解释器仍是 win32 原生构建，看不到这些路径） |
| Python | 3.11.9 (`sys.platform = "win32"`, MinGW build at `C:/Users/GYP/.pilot/environment/mingw64/bin/python.exe`) |
| matplotlib | 未安装（visualizer 自动降级到 stdlib PNG 后端） |
| psutil | 未安装（RSS 测量走 `tasklist /FO CSV` fallback；本次未触发） |

### A.2 数据源探测结论

| 探测项（从 Python 视角） | 结果 | 影响 |
|---|---|---|
| `os.path.isdir("/sys/class/power_supply")` | False | `SysfsPowerSource.is_available()` → False，回退到 `DummySource` |
| `os.path.isfile("/proc/stat")` | False | `ProcfsProbe.is_available()` → False |
| `os.path.isfile("/proc/meminfo")` | False | 同上 |
| `os.path.isdir("/sys/class/thermal")` | False | 无温度传感器 |
| `import psutil` | ModuleNotFoundError | `PsutilProbe.is_available()` → False |
| `select_default_probe(("procfs","psutil"))` | 实际返回 `DummyProbe` | 预期行为 |
| `select_default_source(("sysfs",))` | 实际返回 `DummySource` | 预期行为 |

**结论**：本次运行**不构成**真实硬件验证。结果只用于确认"在没有任何真实数据源时全链路依然能跑通"。真实数据源验证必须在边缘设备上重新执行（见 §B）。

### A.3 运行命令与产物

```bash
PYTHONIOENCODING=utf-8 python integration/test_e2e_collect_to_report.py \
    --duration-sec 30 --interval-ms 1000 \
    --output-dir docs/test_report/artifacts
```

| 产物 | 路径 | 大小 |
|---|---|---|
| 报告图 | `docs/test_report/artifacts/test_report.png` | 2607 字节 |
| JSON sidecar | `docs/test_report/artifacts/test_report.png.json` | 含完整 `WindowSummary` + `_render_backend="stdlib"` |

PNG 头校验通过（`\x89PNG\r\n\x1a\n`），sidecar 包含 `timeline_cpu`/`timeline_power_watt` 等所有必备字段。

### A.4 关键指标（来自 stdout JSON）

| 指标 | 值 | 备注 |
|---|---|---|
| result | **PASS** | 0 失败项 |
| duration_sec / interval_ms | 30 / 1000 | 1 Hz × 30 秒 |
| probe_name / power_source_name | dummy / dummy | 真实源全部不可用，按预期降级 |
| metrics_count / power_count | 32 / 33 | DURATION-1 的下限是 29，远超 |
| cpu_avg / cpu_p95 / cpu_max (%) | 12.05 / 13.50 / 13.87 | DummyProbe 合成值，应在 base±jitter 区间内（base=12, jitter=2）✓ |
| power_avg / power_p95 / power_max (W) | 7.97 / 8.78 / 8.98 | DummySource 合成值，应在 base±jitter 区间内（base=8, jitter=1）✓ |
| energy_joule | 252.91 | 平均功率 × 累积窗口跨度，单调增长✓ |
| power_quality_worst | raw | DummySource 全部返回 `quality=raw`，无降级 |
| render_backend | stdlib | matplotlib 不可用时的回退路径 |
| failures | `[]` | 无字段违规、无样本欠数 |

### A.5 已知问题与跟进

1. **真实源未触达**：本运行不能证明 `SysfsPowerSource` / `ProcfsProbe` 在真实硬件上的稳定性。需在 §B 步骤中执行。
2. **stdlib PNG 后端**：当前回退后端只画线段，不带坐标标签和注释文字。CI 通过没问题，但人眼复核需要在装有 matplotlib 的环境（无论开发机还是边缘设备）重跑。
3. **温度字段恒为 None**：DummyProbe 不模拟温度，预期行为；真实设备上 `ProcfsProbe._read_temp()` 会读取 `/sys/class/thermal/thermal_zone0/temp`。
4. **CLI 默认行为已改**：`--duration-sec` 默认 30、`--output-dir` 默认 `integration/`、不带 `--force-dummy` 时优先尝试真实源。无参数调用仍兼容（10s 默认走 `integration/`）。

### A.6 本节判定

- 端到端代码路径无报错：✅
- 报告 PNG 与 sidecar 落盘且通过头校验：✅
- 各模块降级路径符合设计：✅
- **不构成真实硬件验收**：⚠️ 必须在 §B 完成后才能签收

---

## A.7 模拟场景验证（无真实硬件时的能力预演）

> 真实设备暂时不在手边，但端到端管线已经具备区分不同负载形态的能力。本节用合成的 `Scenario` 驱动 `DummyProbe` + `DummySource`，让"采集→分析→可视化"链路在三种典型工作负载下各跑 60 秒，输出可对比的报告。**这不是真实硬件验收**，但它能证明：当真实数据接入时，分析层会做出符合预期的反应。

### A.7.1 场景定义（`src/scenarios/`）

| 场景 | CPU 形态 | 功耗形态 | 温度峰值 | 设计意图 |
|---|---|---|---|---|
| **idle** | 均值 5%（低抖动） | 均值 2W | ~39°C | 设备空闲基线 |
| **inference** | 均值 75%，每 12s 周期性尖峰至 ~95% | 均值 8W，跟随尖峰小幅上升 | ~63°C | 模型推理稳态负载 |
| **throttled** | 0~20s 从 50% 爬升到 95%，20~40s 因热墙跌回 ~60%（带衰减振荡），40~60s 平台期 | 与 CPU 同步爬升然后跌落 | ~80°C 后回落 | 验证降频与跨指标关联识别 |

每个 `Scenario` 共享给同一组 `DummyProbe` 和 `DummySource`，所以 CPU/温度（platform 路径）与功耗（power 路径）在时间轴上严格相位锁定——这正好是真实设备应有的相关性。

### A.7.2 运行命令

```bash
PYTHONIOENCODING=utf-8 python examples/generate_scenario_reports.py --duration-sec 60
```

每场景 1Hz × 60s × 双路采样 → `AggregatorAnalyzer.get_summary_dict()` → `plot_report()`。

### A.7.3 实测结果（本次运行）

| 场景 | cpu_avg | cpu_max | pwr_avg | pwr_max | energy(J) | temp_max | 报告 PNG |
|---|---:|---:|---:|---:|---:|---:|---|
| idle      |  4.94% |  5.99% | 1.97W | 2.15W | 121.97 | 38.80°C | [report_idle.png](scenarios/report_idle.png) |
| inference | 76.41% | 95.98% | 8.09W | 9.17W | 493.57 | 63.83°C | [report_inference.png](scenarios/report_inference.png) |
| throttled | 63.69% | 92.26% | 5.99W | 8.81W | 337.59 | 79.97°C | [report_throttled.png](scenarios/report_throttled.png) |

完整逐字段汇总：[scenarios/scenario_summary.json](scenarios/scenario_summary.json)

每张报告都生成 `<report>.png.json` sidecar，里面是被绘制的完整 `WindowSummary`（含 `timeline_*` 短序列），CI 或人工复核可以直接读 JSON 比对。

### A.7.4 与设计目标的对照

- **idle 场景**：cpu_avg 4.94% vs 目标 5%（误差 1.2%），pwr_avg 1.97W vs 目标 2W（误差 1.5%）。✅
- **inference 场景**：cpu_avg 76.41% vs 目标 75%，cpu_max 95.98% 来自每 12 秒一次的 +18% 尖峰（目标 ~95%）；pwr_avg 8.09W vs 目标 8W；尖峰跟随 CPU 在 ~9W 出现。✅
- **throttled 场景**：cpu_max 92.26% 出现在 0~20s 爬坡末段（接近目标 95%），cpu_avg 63.69% 反映"先冲高再稳态降频"的整体均值（目标 60% 平台期，因为前 20s 高负载拉高了均值）；temp_max 79.97°C 触发热墙（设计阈值 80°C）后 CPU 跌至 60% 平台期、功耗对应跌至 ~5W。✅
- **能量对比**：493.57J（inference）> 337.59J（throttled）> 121.97J（idle）——同样 60s 时长下，能量积分严格遵循"持续高负载 > 受限高负载 > 空闲"的预期。✅

### A.7.5 这能证明什么 / 不能证明什么

能证明：
- 双路采样（platform + power）在共享相位的负载上不会丢帧、不会错位；3 个场景每个都收满 60+ 帧。
- `AggregatorAnalyzer` 在三种差异显著的输入分布上，给出的 cpu_avg / cpu_p95 / cpu_max / power_max / energy_joule / temp_max 字段都能区分得开（idle 与 inference 的 cpu_avg 差 15 倍）。
- visualizer 的 stdlib PNG 后端能在 5KB 以内为每个场景生成可机器校验的报告（PNG header + sidecar JSON）；当真实设备装有 matplotlib 时，相同的 summary 会自动得到带坐标轴标签和文字注释的可读图。
- 跨指标关联：throttled 场景中 temp_max 越线 → cpu/power 同步回落，证明"温度墙触发降频"这种最常见的边缘设备故障模式，在我们的报告里是肉眼可识别的。

不能证明：
- 真实传感器的读取延迟、抖动、失败率（这些只能在 §B 真机执行）。
- `SysfsPowerSource` / `ProcfsProbe` 的实测路径正确性。
- 热墙触发的物理时序（这里是脚本预设的 20s）；真实设备上时序由温控曲线决定。

### A.7.6 给真机执行者的指引

执行 §B 真机验收时，可以**复用同一脚本**（`examples/generate_scenario_reports.py`）作为对照基线：在 dummy 场景的报告 PNG 旁边放上真机 30 秒 e2e 的报告，肉眼就能判断真机数据是否落在合理范围（idle ~ throttled）之内。如果真机 idle 时报出的 cpu_avg 是 60%，那一定是采集逻辑或主机负载有问题。

---

## B. 真实设备验收操作手册（待执行）

> 本节是"操作清单 + 待填表格"，用于在三类目标设备上各跑一次 30 秒以上的端到端验证，记录真实指标并判定 PASS/FAIL。每张表格在执行前都是空白；执行后由操作者填入实测数据并提交回仓库。

### B.1 通用前置

设备清单（v1 验收覆盖范围）：
- Jetson Nano（4GB / 2GB）
- Raspberry Pi 4B（2GB+）
- 任一 x86 边缘服务器（Ubuntu 20.04+ 或同等）

每台设备的最小依赖：
- Python 3.8+
- 可选 `psutil`（推荐，温度传感器更全）
- 可选 `matplotlib`（用于人眼复核报告图）
- 不需要 `jetson-stats`、`tegrastats` 即可跑通主链路；后者将在后续 sprint 接入。

### B.2 上传项目到设备

二选一：

**选项 A — SCP 整目录**
```bash
# 在开发机
ssh-keygen -t ed25519 -C "ai-edge-monitor"   # 若已有 key 可跳过
ssh-copy-id <user>@<device-ip>

scp -r ai-embedded-hw-monitoring \
    <user>@<device-ip>:~/ai-edge-monitor
```

**选项 B — git clone（推荐）**
```bash
# 在设备
cd ~
git clone <repo-url> ai-edge-monitor
cd ai-edge-monitor
git checkout <commit-or-branch-under-test>
```

### B.3 设备端环境检查

在设备上执行：

```bash
cd ~/ai-edge-monitor

python3 - <<'PY'
import os, platform, sys
print("python", sys.version.split()[0], "platform", sys.platform)
print("uname", platform.uname())
for p in ("/proc/stat", "/proc/meminfo"):
    print(f"{p}: readable={os.path.isfile(p)}")
print("sysfs power_supply:", os.path.isdir("/sys/class/power_supply"),
      "entries:", os.listdir("/sys/class/power_supply") if os.path.isdir("/sys/class/power_supply") else "n/a")
print("thermal:", os.path.isdir("/sys/class/thermal"))
try:
    with open("/proc/device-tree/model","rb") as f: print("dt-model:", f.read().decode("ascii", "replace").strip("\x00"))
except FileNotFoundError: print("dt-model: n/a")
PY
```

**填表（每台设备一份）**：

| 项 | Jetson Nano | RPi 4B | x86 边缘 |
|---|---|---|---|
| 设备型号 / DT model | _待填_ | _待填_ | _待填_ |
| OS 版本 | _待填_ | _待填_ | _待填_ |
| Python 版本 | _待填_ | _待填_ | _待填_ |
| `/proc/stat` 可读 | _待填_ | _待填_ | _待填_ |
| `/proc/meminfo` 可读 | _待填_ | _待填_ | _待填_ |
| `/sys/class/power_supply` 存在 | _待填_ | _待填_ | _待填_ |
| sysfs 子项（如 BAT0/AC0） | _待填_ | _待填_ | _待填_ |
| `psutil` 已安装 | _待填_ | _待填_ | _待填_ |
| `matplotlib` 已安装 | _待填_ | _待填_ | _待填_ |

### B.4 跑基线 + 各模块 integration（防回归）

```bash
cd ~/ai-edge-monitor
PYTHONIOENCODING=utf-8 python3 tests/power_monitor/test_baseline.py
PYTHONIOENCODING=utf-8 python3 tests/platform_adapter/test_baseline.py
PYTHONIOENCODING=utf-8 python3 tests/aggregator_analyzer/test_baseline.py
PYTHONIOENCODING=utf-8 python3 integration/test_power_to_analyzer.py | tail -5
PYTHONIOENCODING=utf-8 python3 integration/test_adapter_to_collector.py | tail -5
```

预期：每条命令最后输出 `PASS` 或 `INTEGRATION RESULT: PASS`。失败则记录到 §B.7。

### B.5 跑 30 秒真实源端到端

```bash
mkdir -p docs/test_report/artifacts
PYTHONIOENCODING=utf-8 python3 integration/test_e2e_collect_to_report.py \
    --duration-sec 30 --interval-ms 1000 \
    --output-dir docs/test_report/artifacts \
  | tee docs/test_report/artifacts/e2e_<device>.log
```

把日志中的 JSON 块完整粘进下表。

**填表**：

| 字段 | Jetson Nano | RPi 4B | x86 边缘 |
|---|---|---|---|
| `result` | _待填_ | _待填_ | _待填_ |
| `probe_name` | 期望 `procfs` 或 `psutil` | 同左 | 同左 |
| `power_source_name` | 期望 `sysfs`（若设备暴露） | 同左 | 同左 |
| `metrics_count` / `power_count` | _待填_ ≥ 29 | _待填_ ≥ 29 | _待填_ ≥ 29 |
| `cpu_avg` / `cpu_p95` / `cpu_max` (%) | _待填_ | _待填_ | _待填_ |
| `power_avg_watt` / `power_p95_watt` / `power_max_watt` | _待填_ | _待填_ | _待填_ |
| `energy_joule` | _待填_ | _待填_ | _待填_ |
| `power_quality_worst` | 期望 `raw` 或 `derived` | 同左（若无传感器允许 `unavailable`） | 同左 |
| `render_backend` | _待填_ | _待填_ | _待填_ |
| 报告 PNG 大小（字节） | _待填_ | _待填_ | _待填_ |
| 报告 PNG 是否可视化打开正常 | _待填_ | _待填_ | _待填_ |

### B.6 合理范围与判定

判定 PASS 的条件（每台设备独立判断）：

1. **基线测试通过**：`tests/*/test_baseline.py` 三条全部 `PASS`（CPU 增量 < 5ms / RSS 增量 < 5MB）。
2. **样本数达标**：`metrics_count >= 29` 且 `power_count >= 29`（30 秒 ×1Hz，允许 1 帧抖动损失）。
3. **CPU 读数合理性**：
   - `0.0 ≤ cpu_avg ≤ 100.0`，`cpu_max ≤ 100.0`；
   - 若设备处于"空载"，`cpu_avg` 通常 < 30%；
   - 首样接近 0% 是预期（`/proc/stat` 增量法没有上一次基线）。
4. **功耗读数合理性**：
   - Jetson Nano：典型 `2~10 W`（待机 ~2 W，CPU 满载 ~10 W）；
   - RPi 4B：典型 `2~7 W`；若无 sysfs 节点，`power_quality_worst="unavailable"` 是允许的，但此时验收**降级通过**而非全通过；
   - x86 边缘：跨度大，`5~80 W` 视型号；笔电类设备常 ≥10 W。
5. **质量字段**：
   - 若 `power_source_name="sysfs"`：`power_quality_worst` 应为 `raw`（直读 power_now）或 `derived`（V×I 推导）；
   - 若 `power_source_name="dummy"`：判定为**降级通过**，必须在 §B.7 列出"该设备未提供真实功耗节点"。
6. **报告产物**：
   - `test_report.png` 存在，PNG header `\x89PNG\r\n\x1a\n` 校验通过；
   - sidecar JSON 含 `timeline_cpu` 与 `timeline_power_watt`；
   - 若装有 matplotlib，期望 `_render_backend="matplotlib"`，否则 `stdlib` 也算通过。
7. **无回归**：§B.4 的所有命令尾部输出 `PASS`。

满足全部 7 项 → **PASS**；若 §5 走"降级通过"分支 → **PASS-DEGRADED**（视设备硬件能力而定，但需在报告中标注）；任一项失败 → **FAIL**，按 §B.7 记录。

### B.7 异常处理与现场修复指引

| 现象 | 第一步排查 | 修复方向（仓库内） |
|---|---|---|
| `select_default_source` 返回 `dummy` 但设备明明有电池 | 列出 `/sys/class/power_supply/<entry>/` 内容；确认 `power_now` / `current_now` / `voltage_now` 可读 | 在 `src/power_monitor/source.py` 的 `SysfsPowerSource._probe()` 里检查目录扫描逻辑；必要时补充对配置项 `power.preferred_supply` 的支持 |
| `read_once()` 返回 `status=parse_error` | `cat` 实际文件确认是否纯整数（部分驱动会写非数字字符） | 在 `_read_int_file` 加宽容处理（剥离非数字尾缀），或在文档里明确兼容性矩阵 |
| `cpu_percent` 永远是 0% | 是否每次都新建 `ProcfsProbe`？增量法需要保留 `_prev_cpu` | 检查调用方是否复用同一实例；若必须每次新建，考虑在 probe 里加一次 7~10 ms 的 fallback 内部双采 |
| `mem_used_mb` 异常大于 `mem_total_mb` | `/proc/meminfo` 字段顺序在某些内核上不同 | 用 `dict` 解析并显式取 `MemTotal`/`MemAvailable`，已实现，复核读取顺序 |
| `latency_ms` P95 > 5ms | 是否在采样线程内做了重计算？或文件描述符没缓存 | 检查 sampler 里有无意外的统计计算；必要时在 probe 缓存 `open()` 的 fd（trade-off：fd 生命周期管理变复杂） |
| 报告打开是"空白图" | `timeline_cpu` 是否为空？matplotlib 是否被 headless 后端拒绝 | sidecar JSON 里看 `timeline_*`；若空，先确认 `analyzer.get_summary_dict()` 收到的样本数；后端问题强制 `matplotlib.use("Agg")` 已默认 |
| 报告头不是 PNG | sidecar 是否落盘成功？是否磁盘空间不足 | 打印 `out_path.parent`，确认目录可写；磁盘满时 sidecar 也会失败 |

### B.8 最终交付

执行完 §B.3 ~ §B.7 后，把以下产物提交回仓库：

```
docs/test_report/artifacts/test_report_jetson_nano.png
docs/test_report/artifacts/test_report_jetson_nano.png.json
docs/test_report/artifacts/test_report_rpi4b.png
docs/test_report/artifacts/test_report_rpi4b.png.json
docs/test_report/artifacts/test_report_x86_edge.png
docs/test_report/artifacts/test_report_x86_edge.png.json
docs/test_report/artifacts/e2e_jetson_nano.log
docs/test_report/artifacts/e2e_rpi4b.log
docs/test_report/artifacts/e2e_x86_edge.log
```

并在本文件 §B.3 ~ §B.5 的填表区填写实测值，最后在 §B 末尾追加：

```
### B.9 三平台验收结论
- Jetson Nano: PASS / PASS-DEGRADED / FAIL（原因）
- RPi 4B:     PASS / PASS-DEGRADED / FAIL（原因）
- x86 边缘:   PASS / PASS-DEGRADED / FAIL（原因）
- 签收人 / 日期: _____________
```

签收人填写后，验收闭环。

---

## 附录：本次冒烟测试涉及的命令总览

```bash
# 环境探测
test -d /sys/class/power_supply && echo yes || echo no
test -r /proc/stat /proc/meminfo

# 30 秒端到端
PYTHONIOENCODING=utf-8 python integration/test_e2e_collect_to_report.py \
    --duration-sec 30 --interval-ms 1000 \
    --output-dir docs/test_report/artifacts

# 默认参数回归（10s）
PYTHONIOENCODING=utf-8 python integration/test_e2e_collect_to_report.py
```
