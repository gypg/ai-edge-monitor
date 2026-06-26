# 子规格 — 推理框架集成

> 关联验收标准：`acceptance-criteria.md` Phase 1

---

## 1. 概述

创建 `src/inference_monitor/` 模块，提供对 TensorRT、ONNX Runtime、TFLite 推理框架的自动监控包装。

---

## 2. InferenceMonitor 上下文管理器

### 2.1 接口设计

```python
class InferenceMonitor:
    """包装推理调用，自动关联硬件指标。"""

    def __init__(
        self,
        model_path: str,
        framework: str = "auto",  # "auto" | "tensorrt" | "onnxruntime" | "tflite"
        power_source: Optional[str] = None,
        gpu_monitor: bool = True,
    ) -> None: ...

    def __enter__(self) -> "InferenceMonitor": ...
    def __exit__(self, *exc: Any) -> None: ...

    @property
    def results(self) -> InferenceResults: ...
```

### 2.2 数据结构

```python
@dataclass
class InferenceResults:
    model_path: str
    framework: str
    total_inferences: int
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    fps: float
    gpu_util_avg: Optional[float]
    gpu_mem_peak_mb: Optional[float]
    power_avg_watt: Optional[float]
    energy_joule: Optional[float]
    temperature_peak_c: Optional[float]
    layer_profile: Optional[List[LayerProfile]]  # TensorRT only
```

```python
@dataclass
class LayerProfile:
    name: str
    avg_time_ms: float
    calls: int
```

### 2.3 使用示例

```python
with InferenceMonitor("model.trt", framework="tensorrt") as mon:
    for frame in video_stream:
        output = engine.infer(frame)
        mon.record_inference()

results = mon.results
print(f"FPS: {results.fps:.1f}, P95: {results.latency_p95_ms:.1f}ms")
```

---

## 3. TensorRT Profiler 集成

### 3.1 实现方式

- 实现 `trt.IProfiler` 接口
- 在 `report_layer_time()` 中记录每层耗时
- 将层耗时与当前 GPU 利用率/功耗关联

### 3.2 降级策略

```python
try:
    import tensorrt as trt
    HAS_TENSORRT = True
except ImportError:
    HAS_TENSORRT = False
```

无 TensorRT 时：
- `InferenceMonitor` 仍可工作（仅记录时间戳 + 硬件指标）
- `layer_profile` 为 `None`
- 日志输出 `WARNING: TensorRT not available, layer profiling disabled`

---

## 4. ONNX Runtime Profiling 集成

### 4.1 实现方式

- 启用 `SessionOptions.enable_profiling = True`
- 推理结束后解析 `prof_*.json` 文件
- 提取每个算子的执行时间

### 4.2 降级策略

同 TensorRT。

---

## 5. 部署就绪评分

### 5.1 评分公式

```
score = (
    fps_score * 0.3 +
    latency_score * 0.3 +
    thermal_score * 0.2 +
    power_score * 0.2
)
```

各子分计算：
- `fps_score = min(100, fps / target_fps * 100)`
- `latency_score = max(0, 100 - (p95_ms - target_ms) * 10)`
- `thermal_score = max(0, 100 - max(0, peak_temp - 70) * 5)`
- `power_score = max(0, 100 - max(0, avg_power - budget_watt) * 10)`

### 5.2 输出

```python
@dataclass
class DeploymentScore:
    total: int           # 0-100
    fps_score: int
    latency_score: int
    thermal_score: int
    power_score: int
    verdict: str         # "ready" | "marginal" | "not_ready"
    bottlenecks: List[str]  # 识别到的瓶颈列表
```

---

## 6. 测试策略

| 测试类型 | 位置 | 说明 |
|----------|------|------|
| 单元测试 | `tests/inference_monitor/test_monitor.py` | Mock 推理框架，验证接口和数据结构 |
| 集成测试 | `integration/test_inference_monitor.py` | Dummy 模式下端到端验证 |
| 性能测试 | `tests/inference_monitor/test_overhead.py` | 验证包装器开销 < 0.1ms/推理 |
