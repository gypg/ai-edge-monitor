# 子规格 — C++ 原生采集守护进程

> 关联验收标准：`acceptance-criteria.md` Phase 5

---

## 1. 概述

创建 `native/` 目录，包含用 C++ 实现的高性能指标采集守护进程。通过 pybind11 桥接，Python 编排层可以透明调用。

**目标**：在 ARM 边缘设备上，将 `/proc` 读取 + 统计计算的开销降低到 Python 的 1/10 以下。

---

## 2. C++ 采集核心

### 2.1 目录结构

```
native/
├── CMakeLists.txt
├── toolchains/
│   ├── aarch64-linux-gnu.cmake    # Jetson 交叉编译
│   ├── arm-linux-gnueabihf.cmake  # Raspberry Pi 32-bit
│   └── x86_64-linux-gnu.cmake     # x86 本机编译
├── src/
│   ├── proc_reader.h / .cpp       # /proc/stat, /proc/meminfo 读取
│   ├── neon_stats.h / .cpp        # NEON 加速统计计算
│   ├── collector.h / .cpp         # 采集主循环
│   └── main.cpp                   # 守护进程入口
├── bindings/
│   └── pybind_module.cpp          # pybind11 绑定
├── tests/
│   ├── test_proc_reader.cpp
│   ├── test_neon_stats.cpp
│   └── test_collector.cpp
└── bench/
    └── bench_collector.cpp        # Google Benchmark 性能测试
```

### 2.2 核心接口

```cpp
// proc_reader.h
struct RawMetrics {
    double cpu_percent;
    double mem_used_mb;
    double mem_total_mb;
    double temperature_c;
    int64_t timestamp_ms;
    double latency_ms;
    const char* status;  // "ok" | "io_error" | "parse_error"
};

class ProcReader {
public:
    RawMetrics read();
    RawMetrics read_gpu();  // 调用 nvidia-smi（如可用）
};
```

```cpp
// neon_stats.h
class NeonStats {
public:
    // 使用 NEON SIMD 加速的滑窗统计
    void ingest(double value);
    double p95() const;
    double mean() const;
    double max() const;
    size_t count() const;
};
```

### 2.3 NEON 加速

关键热路径使用 ARM NEON intrinsics：

```cpp
// neon_stats.cpp
#include <arm_neon.h>

double NeonStats::p95() const {
    // 1. 将 deque 数据拷贝到对齐的 float64x2_t 数组
    // 2. 使用 NEON 进行部分排序（nth_element 的 NEON 优化版本）
    // 3. 返回第 95 百分位值
}
```

### 2.4 交叉编译

```bash
# Jetson (aarch64)
cmake -DCMAKE_TOOLCHAIN_FILE=toolchains/aarch64-linux-gnu.cmake ..
make -j$(nproc)

# Raspberry Pi (armhf)
cmake -DCMAKE_TOOLCHAIN_FILE=toolchains/arm-linux-gnueabihf.cmake ..
make -j$(nproc)

# x86 本机
cmake ..
make -j$(nproc)
```

---

## 3. pybind11 桥接

### 3.1 Python 接口

```python
# src/native_collector/__init__.py
try:
    from _native_collector import NativeProbe
    HAS_NATIVE = True
except ImportError:
    HAS_NATIVE = False
    NativeProbe = None  # type: ignore
```

### 3.2 接口兼容性

`NativeProbe` 实现与 `PlatformProbe` 相同的接口：

```python
class NativeProbe:
    def read_metrics(self) -> RawMetrics:
        """与 Python PlatformProbe 接口完全一致。"""
        ...
```

### 3.3 自动回退

```python
def select_probe(force_native: bool = False) -> PlatformProbe:
    """自动选择最优探针：Native > Procfs > Psutil > Dummy。"""
    if force_native and HAS_NATIVE:
        return NativeProbe()
    if HAS_NATIVE:
        return NativeProbe()
    # 回退到 Python 实现
    return select_default_probe()
```

---

## 4. 测试策略

| 测试类型 | 位置 | 说明 |
|----------|------|------|
| C++ 单元测试 | `native/tests/` | GoogleTest，验证 proc_reader 和 neon_stats |
| C++ 性能测试 | `native/bench/` | Google Benchmark，验证 NEON 加速效果 |
| Python 集成测试 | `tests/native_collector/` | 验证 pybind11 接口和自动回退 |
| 交叉编译 CI | `.github/workflows/native.yml` | aarch64 + x86_64 编译验证 |

### 4.1 性能对比测试

```python
def test_native_vs_python_performance():
    """C++ NativeProbe 应比 Python ProcfsProbe 快 10x 以上。"""
    python_probe = ProcfsProbe()
    native_probe = NativeProbe()

    python_times = benchmark(python_probe, iterations=1000)
    native_times = benchmark(native_probe, iterations=1000)

    speedup = python_times.mean / native_times.mean
    assert speedup >= 10.0, f"Expected 10x speedup, got {speedup:.1f}x"
```

---

## 5. 构建约束

- C++17 标准
- 不引入 Boost 等重型依赖
- pybind11 通过 `FetchContent` 或 git submodule 引入
- GoogleTest 同上
- 交叉编译工具链文件必须在 `native/toolchains/` 中
- CMake 最低版本 3.16
