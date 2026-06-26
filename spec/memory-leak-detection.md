# 子规格 — 内存泄漏检测与崩溃诊断

> 关联验收标准：`acceptance-criteria.md` Phase 3

---

## 1. 概述

创建 `src/memory_diagnostics/` 模块，提供：
- RSS 内存线性增长检测（泄漏预警）
- GPU 显存泄漏关联分析
- Debug Bundle 自动生成（崩溃诊断信息采集）
- 信号处理器包装（SIGSEGV/SIGABRT 捕获）

---

## 2. RSS 线性增长检测

### 2.1 算法

使用简单线性回归检测 RSS 趋势：

```python
class LeakDetector:
    """基于 RSS 时间序列的内存泄漏检测器。"""

    def __init__(
        self,
        window_size: int = 60,          # 采样窗口大小
        r_squared_threshold: float = 0.8,  # 线性拟合 R² 阈值
        slope_threshold_mb_per_sec: float = 0.1,  # 最小泄漏速率
    ) -> None: ...

    def observe(self, rss_mb: float, timestamp_ms: int) -> Optional[LeakAlert]: ...
```

### 2.2 泄漏告警

```python
@dataclass
class LeakAlert:
    target_pid: int
    target_name: str
    r_squared: float           # 拟合优度
    slope_mb_per_sec: float    # 泄漏速率
    estimated_time_to_oom: Optional[float]  # 预计 OOM 时间（秒）
    window_start_ms: int
    window_end_ms: int
    sample_count: int
```

### 2.3 无泄漏时

- `observe()` 返回 `None`
- 不分配额外内存（使用固定大小 `deque(maxlen=window_size)`）

---

## 3. GPU 内存泄漏关联

### 3.1 同时追踪

```python
class GpuMemoryTracker:
    """关联 CPU RSS 与 GPU 显存变化。"""

    def observe(
        self,
        rss_mb: float,
        gpu_mem_mb: Optional[float],
        timestamp_ms: int,
    ) -> Optional[GpuLeakAlert]: ...
```

### 3.2 关联分析

| 模式 | 含义 | 告警 |
|------|------|------|
| RSS↑ + GPU↑ | 双通道泄漏 | CRITICAL |
| RSS↑ + GPU→ | 仅 CPU 泄漏 | WARNING |
| RSS→ + GPU↑ | 仅 GPU 泄漏 | WARNING |
| RSS→ + GPU→ | 无泄漏 | None |

---

## 4. Debug Bundle 生成

### 4.1 触发条件

- RSS 泄漏告警触发
- GPU 泄漏告警触发
- 手动调用 `generate_debug_bundle(pid)`

### 4.2 Bundle 内容

```python
def generate_debug_bundle(pid: int, output_dir: Path) -> Path:
    """生成调试信息包。"""
    # 1. /proc/<pid>/status → 进程状态
    # 2. /proc/<pid>/maps → 内存映射
    # 3. /proc/<pid>/smaps_rollup → 内存汇总
    # 4. dmesg 最后 100 行 → 内核消息（OOM kill 等）
    # 5. RSS 时间序列 CSV
    # 6. GPU 显存时间序列 CSV（如可用）
    # 7. 诊断结论 JSON
```

### 4.3 输出格式

```
debug_bundle_<pid>_<timestamp>/
├── proc_status.txt
├── proc_maps.txt
├── smaps_rollup.txt
├── dmesg_tail.txt
├── rss_timeline.csv
├── gpu_mem_timeline.csv
└── diagnosis.json
```

### 4.4 约束

- 生成时间 < 1 秒
- 总大小 < 10MB
- 敏感信息不写入（密码、密钥等）

---

## 5. 信号处理器包装

### 5.1 实现

```python
class CrashHandler:
    """捕获 SIGSEGV/SIGABRT，在崩溃前生成诊断信息。"""

    def install(self, pid: int) -> None: ...
    def uninstall(self) -> None: ...
```

### 5.2 捕获的信号

| 信号 | 行为 |
|------|------|
| `SIGSEGV` | 生成 debug bundle → 恢复默认处理 → 重新发送信号 |
| `SIGABRT` | 生成 debug bundle → 恢复默认处理 → 重新发送信号 |
| `SIGTERM` | 优雅关闭：停止采集 → 生成最终报告 |

### 5.3 限制

- 仅在 Linux 上可用（Windows 无 SIGSEGV 处理）
- 信号处理器中不能使用 Python 分配内存（只能用 async-signal-safe 操作）
- 降级方案：无法安装信号处理器时，仅记录 WARNING 日志

---

## 6. 测试策略

| 测试类型 | 位置 | 说明 |
|----------|------|------|
| 单元测试 | `tests/memory_diagnostics/test_leak_detector.py` | 构造线性/稳态/随机数据，验证检出率和误报率 |
| 单元测试 | `tests/memory_diagnostics/test_gpu_tracker.py` | 验证 4 种关联模式 |
| 单元测试 | `tests/memory_diagnostics/test_debug_bundle.py` | Mock `/proc` 文件，验证 bundle 内容 |
| 集成测试 | `integration/test_memory_diagnostics.py` | Dummy 模式下端到端验证 |
| 性能测试 | `tests/memory_diagnostics/test_overhead.py` | 检测器自身 RSS < 1MB |
