# Power Monitor Skeleton & Baseline Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Python 3.8+ 下实现 `src/power_monitor/` 模块骨架与 `tests/power_monitor/test_baseline.py` 基准测试脚本，并可直接运行给出 PASS/FAIL。

**Architecture:** 采用小而清晰的四文件模块划分：`source.py` 负责采集源抽象与 DummySource，`sampler.py` 负责 monotonic+sleeep 非忙等采样循环，`stats.py` 负责滑动窗口统计，`__init__.py` 负责导出公共接口。测试脚本独立验证 DummySource 空跑开销与阈值判定。

**Tech Stack:** Python 3.8+, 标准库（time/threading/collections/statistics/dataclasses/typing）, psutil（可选但推荐）

---

## File Structure

- Create: `src/power_monitor/__init__.py` — 暴露公开 API（PowerSource, DummySource, PowerSampler, PowerStats 等）
- Create: `src/power_monitor/source.py` — 功耗读取数据结构、抽象基类、DummySource 最小实现
- Create: `src/power_monitor/sampler.py` — 非忙等采样循环与样本回调
- Create: `src/power_monitor/stats.py` — 滑动窗口统计（avg/max/min/p95/energy）
- Create: `tests/power_monitor/test_baseline.py` — 30秒、100ms 间隔的开销验收脚本（打印+PASS/FAIL）

---

### Task 1: 建立 source 抽象与 DummySource

**Files:**
- Create: `src/power_monitor/source.py`

- [ ] **Step 1: 写失败测试（导入与基础行为）**

```python
from power_monitor.source import DummySource

def test_dummy_source_read_once_returns_ok_reading():
    src = DummySource()
    reading = src.read_once(timeout_ms=50)
    assert reading.status == "ok"
    assert reading.power_watt is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/power_monitor/test_baseline.py -q`
Expected: FAIL with ImportError / module not found

- [ ] **Step 3: 最小实现 source.py**

```python
from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Optional, Literal
import random, time

Quality = Literal["raw", "derived", "estimated", "unavailable"]
ReadStatus = Literal["ok", "timeout", "io_error", "parse_error", "not_supported"]

@dataclass
class PowerReading:
    ts_ms: int
    power_watt: Optional[float]
    voltage_v: Optional[float]
    current_a: Optional[float]
    source_name: str
    quality: Quality
    status: ReadStatus
    latency_ms: float

class PowerSource(ABC):
    @abstractmethod
    def is_available(self) -> bool: ...
    @abstractmethod
    def read_once(self, timeout_ms: int) -> PowerReading: ...

class DummySource(PowerSource):
    ...
```

- [ ] **Step 4: 再次运行测试确认通过**

Run: `python -m pytest tests/power_monitor/test_baseline.py -q`
Expected: PASS (针对 DummySource 的基础断言)

- [ ] **Step 5: Commit**

```bash
git add src/power_monitor/source.py
git commit -m "feat: add power source abstraction and dummy source"
```

### Task 2: 实现 PowerSampler 非忙等采样循环

**Files:**
- Create: `src/power_monitor/sampler.py`

- [ ] **Step 1: 写失败测试（采样计数）**

```python
from power_monitor.sampler import PowerSampler
from power_monitor.source import DummySource

def test_sampler_collects_samples_without_busy_wait():
    src = DummySource()
    sampler = PowerSampler(source=src, interval_ms=100)
    sampler.start()
    time.sleep(0.35)
    sampler.stop()
    assert sampler.sample_count >= 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/power_monitor/test_baseline.py -q`
Expected: FAIL with ImportError for sampler

- [ ] **Step 3: 最小实现 sampler.py**

```python
import time, threading

class PowerSampler:
    def _run_loop(self):
        next_tick = time.monotonic()
        while not self._stop_event.is_set():
            now = time.monotonic()
            sleep_s = max(0.0, next_tick - now)
            if sleep_s > 0:
                time.sleep(sleep_s)
            reading = self.source.read_once(self.timeout_ms)
            ...
            next_tick += self.interval_ms / 1000.0
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/power_monitor/test_baseline.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/power_monitor/sampler.py
git commit -m "feat: add non-busy-wait power sampler loop"
```

### Task 3: 实现 PowerStats 滑动窗口统计

**Files:**
- Create: `src/power_monitor/stats.py`

- [ ] **Step 1: 写失败测试（窗口统计）**

```python
from power_monitor.stats import PowerStats

def test_power_stats_computes_avg_and_p95():
    stats = PowerStats(window_size=5)
    for v in [1,2,3,4,5]:
        stats.ingest_power(v, ts_ms=0)
    out = stats.snapshot()
    assert out["avg_power_watt"] == 3.0
    assert out["p95_power_watt"] >= 4.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/power_monitor/test_baseline.py -q`
Expected: FAIL with ImportError for stats

- [ ] **Step 3: 最小实现 stats.py**

```python
from collections import deque

class PowerStats:
    def ingest(self, reading): ...
    def snapshot(self): ...
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/power_monitor/test_baseline.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/power_monitor/stats.py
git commit -m "feat: add sliding-window power stats"
```

### Task 4: 导出模块 API 与编写基准验收脚本

**Files:**
- Create: `src/power_monitor/__init__.py`
- Create: `tests/power_monitor/test_baseline.py`

- [ ] **Step 1: 写失败测试（运行入口）**

```python
def test_baseline_script_runs_and_prints_pass_fail(capsys):
    # 调用 main(duration_sec=2) 缩短测试
    ...
    assert "PASS" in captured or "FAIL" in captured
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/power_monitor/test_baseline.py -q`
Expected: FAIL with missing entrypoint

- [ ] **Step 3: 实现基准脚本（30秒、100ms、打印阈值判定）**

```python
def run_baseline(duration_sec=30, interval_ms=100):
    # process_time / psutil 测CPU与RSS
    # 打印 CPU时间增量 与 常驻内存增量
    # 输出 PASS/FAIL
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python tests/power_monitor/test_baseline.py`
Expected: 输出 `CPU 时间增量: ... ms，常驻内存增量: ... MB` + PASS/FAIL

- [ ] **Step 5: Commit**

```bash
git add src/power_monitor/__init__.py tests/power_monitor/test_baseline.py
git commit -m "test: add power monitor baseline overhead test"
```

### Task 5: 最终验证（Python 3.8+ 可运行性）

**Files:**
- Verify: `src/power_monitor/*.py`
- Verify: `tests/power_monitor/test_baseline.py`

- [ ] **Step 1: 运行单测**

Run: `python -m pytest tests/power_monitor/test_baseline.py -q`
Expected: PASS

- [ ] **Step 2: 运行基准脚本（真实30秒）**

Run: `python tests/power_monitor/test_baseline.py`
Expected: 打印指标与 PASS/FAIL

- [ ] **Step 3: 记录运行说明**

在 `tests/power_monitor/test_baseline.py` 顶部 docstring 说明：
- 依赖：`psutil`
- 运行命令
- 判定阈值含义

- [ ] **Step 4: Commit**

```bash
git add src/power_monitor tests/power_monitor/test_baseline.py
git commit -m "chore: verify power monitor skeleton baseline on py38+"
```
