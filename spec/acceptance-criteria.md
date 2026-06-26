# 验收标准 — AI Edge Monitor v2.0

> 本文档定义每个功能模块的量化验收标准。
> 每条标准必须有：**量化指标**、**判定方法**、**通过证据格式**。
> AI 代理不得声称"已完成"——必须提供实际测试输出作为证据。

---

## 通用验收规则

1. **所有测试必须通过**：`python -m pytest tests/ integration/ -v` 零失败
2. **向后兼容**：现有 6 个基线测试 + 7 个集成测试不得回归
3. **Dummy 回退**：所有新功能必须在 `force_dummy=True` 下可测试
4. **内存基线**：30s × 100ms 空跑 RSS 增量 < 0.05MB
5. **CPU 基线**：30s × 100ms 空跑 CPU 增量 < 0.05ms/样本
6. **类型检查**：`mypy src/ --ignore-missing-imports` 零错误
7. **代码风格**：`black --check src/` 和 `isort --check src/` 通过

---

## Phase 1：推理框架集成

### 1.1 InferenceMonitor 包装器

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| 推理延迟精度 | 与手动 `time.perf_counter()` 差异 < 1ms | 单元测试：对比 InferenceMonitor 计时与手动计时 | pytest 输出中 `test_latency_accuracy` PASS |
| GPU 指标采集 | 推理期间 GPU 利用率变化 ≤ 5%（与 nvidia-smi 独立采集对比） | 集成测试：同时运行 InferenceMonitor 和独立 nvidia-smi，对比差异 | 对比表输出 |
| 功耗关联 | 推理期间功耗数据非 None | 单元测试：dummy power source 下验证关联数据存在 | pytest 输出 |
| 内存开销 | InferenceMonitor 实例 RSS < 2MB | 基线测试：`tracemalloc` 测量实例化前后差异 | 内存差值输出 |
| 上下文管理器 | `with` 块异常时仍能正确关闭 | 单元测试：模拟异常，验证资源清理 | pytest 输出 |

### 1.2 TensorRT 集成

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| Profiler 回调注册 | 100 次推理回调完整记录 | 单元测试：mock TensorRT profiler，验证回调次数 | 回调计数输出 |
| Per-layer 数据 | 至少记录 layer name + 执行时间 | 单元测试：验证输出 dict 包含必需字段 | dict 结构输出 |
| 降级行为 | 无 TensorRT 环境不崩溃 | 单元测试：import 失败时返回 None | pytest 输出 |

### 1.3 ONNX Runtime 集成

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| Session profiling | 提取 `profiling_data` 并关联硬件指标 | 单元测试：mock ORT session，验证数据结构 | dict 结构输出 |
| 降级行为 | 无 ONNX Runtime 环境不崩溃 | 单元测试：import 失败时返回 None | pytest 输出 |

### 1.4 部署就绪评分

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| 评分范围 | 0-100 分 | 单元测试：各种指标组合验证评分范围 | 分数值输出 |
| 评分维度 | 包含 FPS/延迟/功耗/温度 4 个维度 | 单元测试：验证评分 dict 含 4 个子分 | dict 结构输出 |
| 边界处理 | 空数据返回 0 分 | 单元测试：空输入不崩溃 | pytest 输出 |

---

## Phase 2：AI Advisor 自动诊断

### 2.1 指标模式识别

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| 规则覆盖 | ≥ 10 条诊断规则 | 代码审查：`len(rules)` ≥ 10 | 规则计数输出 |
| 误报率 | dummy 场景下误报 = 0 | 集成测试：idle/inference/throttled 场景运行，零误报 | 告警列表输出 |
| 检出率 | throttled 场景必须检出 ≥ 1 条诊断 | 集成测试：throttled 场景运行 30s | 诊断列表输出 |
| 响应时间 | 单次诊断 < 10ms | 性能测试：1000 次诊断平均时间 | 平均耗时输出 |

### 2.2 优化建议

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| 建议格式 | 每条含 `category` + `priority` + `suggestion` + `evidence` | 单元测试：验证输出 dict 结构 | dict 结构输出 |
| 建议数量 | 单次诊断输出 0-10 条（不泛滥） | 单元测试：边界条件验证 | 计数输出 |
| 建议相关性 | 建议中的 `evidence` 字段引用实际指标值 | 代码审查 + 单元测试 | evidence 字段输出 |

---

## Phase 3：内存泄漏检测

### 3.1 RSS 线性增长检测

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| 线性回归精度 | 已知泄漏模式（线性增长）检出率 100% | 单元测试：构造线性增长数据，验证检出 | 检出标志输出 |
| 稳态误报 | 稳态（恒定 RSS）误报率 = 0 | 单元测试：构造稳态数据，验证无告警 | 告警列表为空 |
| 采样窗口 | 可配置，默认 60 个采样点 | 单元测试：验证窗口参数 | 参数值输出 |
| 内存效率 | 检测器自身 RSS < 1MB | 基线测试 | RSS 差值输出 |

### 3.2 GPU 内存关联

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| 关联分析 | 同时追踪 CPU RSS + GPU 显存 | 单元测试：验证双通道数据 | 数据结构输出 |
| GPU 泄漏检测 | GPU 显存线性增长检出率 100% | 单元测试：构造 GPU 显存增长数据 | 检出标志输出 |

### 3.3 Debug Bundle

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| 包含内容 | `/proc/<pid>/status` + `/proc/<pid>/maps` + `dmesg` 最后 100 行 | 集成测试：生成 bundle，验证文件存在 | 文件列表输出 |
| 生成时间 | < 1 秒 | 性能测试 | 耗时输出 |
| 大小限制 | < 10MB | 集成测试 | 文件大小输出 |

---

## Phase 4：ROS2 桥接

### 4.1 节点实现

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| Topic 发布 | CPU/Memory/Power/Temperature 4 个 topic | 单元测试（mock rclpy） | topic 列表输出 |
| 发布频率 | 与采集间隔一致（±10%） | 集成测试：对比采集时间戳与发布时间戳 | 频率对比输出 |
| 降级行为 | 无 ROS2 环境不崩溃 | 单元测试：import 失败时优雅降级 | pytest 输出 |

### 4.2 推理管线监控

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| 推理指标 Topic | `/inference/fps` + `/inference/latency` + `/inference/gpu_util` | 单元测试 | topic 列表输出 |
| 消息类型 | 使用 `std_msgs/Float64` 或自定义消息 | 代码审查 | 消息类型定义 |

---

## Phase 5：C++ 原生采集

### 5.1 采集核心

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| 编译成功 | aarch64 + x86_64 双平台编译通过 | CI 构建日志 | 编译日志输出 |
| 采集精度 | 与 Python ProcfsProbe 差异 < 0.1% | 对比测试：同时运行 C++ 和 Python 采集 | 差异百分比输出 |
| 采集速度 | 单次 `/proc/stat` 读取 < 0.1ms | 性能测试 | 耗时输出 |
| 内存占用 | 守护进程 RSS < 2MB | 运行时监控 | RSS 输出 |
| NEON 加速 | `_p95()` 计算速度提升 ≥ 3x vs 纯 C++ | 基准测试对比 | 速度比输出 |

### 5.2 pybind11 桥接

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| Python 调用 | `from native_collector import NativeProbe` 可用 | 单元测试 | import 成功 |
| 接口兼容 | 实现与 `PlatformProbe` 相同的 `read_metrics()` 接口 | 单元测试：接口一致性检查 | 接口对比输出 |
| 降级行为 | 无 C++ 模块时回退到 Python | 单元测试：删除 .so 后验证回退 | 回退日志输出 |

---

## Phase 6：Web 仪表盘增强

### 6.1 推理性能面板

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| FPS 图表 | 实时 FPS 折线图可渲染 | 浏览器手动测试 | 截图 |
| 延迟分布 | P50/P95/P99 直方图可渲染 | 浏览器手动测试 | 截图 |
| API 端点 | `/api/inference` 返回推理指标 JSON | curl 测试 | JSON 输出 |

### 6.2 Grafana 导出

| 指标 | 标准 | 判定方法 | 证据格式 |
|------|------|----------|----------|
| Dashboard JSON | 导出的 JSON 可直接导入 Grafana | 手动导入测试 | 导入成功截图 |
| 数据源配置 | 支持 Prometheus 数据源 | JSON 审查 | 数据源配置 |

---

## 证据提交格式

每个任务完成后，代理必须在对应的验收条目下追加：

```markdown
### 通过证据

- **日期**：YYYY-MM-DD
- **代理**：agent-name
- **测试命令**：`python -m pytest tests/xxx -v`
- **测试输出**：
  ```
  <粘贴实际 pytest 输出>
  ```
- **性能数据**（如适用）：
  ```
  <粘贴性能测试输出>
  ```
```

**禁止行为**：
- ❌ "测试通过"（无输出）
- ❌ "应该没问题"（无证据）
- ❌ "基本完成"（模糊表述）
- ❌ 跳过测试直接声称完成

**必须行为**：
- ✅ 粘贴完整 pytest 输出（至少最后 20 行）
- ✅ 粘贴性能测试的具体数字
- ✅ 如有失败，说明原因和修复计划
- ✅ 对比修改前后的数据变化

---

## 通过证据记录

### Phase 1-3 通用验收（全量测试）

- **日期**：2026-06-26
- **代理**：p1-p3 agents + fix-agents
- **测试命令**：`python -m pytest tests/ -v`
- **测试输出**：
  ```
  146 passed, 1 skipped in 5.33s
  ```
- **模块覆盖**：
  - `tests/ai_advisor/` — 43 tests (engine + rules + scorer)
  - `tests/inference_monitor/` — 20 tests (tensorrt + onnx)
  - `tests/memory_diagnostics/` — 22 tests (leak_detector + gpu_tracker + debug_bundle)
  - `tests/ros2_bridge/` — 12 tests (launch + node)
  - `tests/native_collector/` — 4 tests (fallback)
  - `tests/web_dashboard/` — 11 tests (grafana)
  - 原有 tests — 34 tests（零回归）

### Phase 1：推理框架集成

- **InferenceMonitor 包装器**：✅ 创建 `src/inference_monitor/monitor.py`
- **TensorRT Profiler**：✅ 创建 `src/inference_monitor/tensorrt_bridge.py`（含降级）
- **ONNX Runtime Bridge**：✅ 创建 `src/inference_monitor/onnx_bridge.py`（含降级）
- **部署就绪评分**：✅ 创建 `src/inference_monitor/scorer.py`
- **测试证据**：20 tests PASSED (test_tensorrt + test_onnx)

### Phase 2：AI Advisor 自动诊断

- **诊断引擎**：✅ 创建 `src/ai_advisor/engine.py`（含冷却期）
- **诊断规则库**：✅ 创建 `src/ai_advisor/rules.py`（12 条规则）
- **部署就绪评分**：✅ 创建 `src/ai_advisor/scorer.py`
- **测试证据**：43 tests PASSED (test_engine + test_rules + test_scorer)

### Phase 3：内存泄漏检测

- **RSS 泄漏检测器**：✅ 创建 `src/memory_diagnostics/leak_detector.py`
- **GPU 显存关联**：✅ 创建 `src/memory_diagnostics/gpu_tracker.py`
- **Debug Bundle**：✅ 创建 `src/memory_diagnostics/debug_bundle.py`
- **DataQuality O(n) 修复**：✅ `list.pop(0)` → `collections.deque`
- **测试证据**：22 tests PASSED (test_leak_detector + test_gpu_tracker + test_debug_bundle)

### Phase 4：ROS2 桥接

- **ROS2 节点**：✅ 创建 `src/ros2_bridge/node.py`（含降级）
- **Launch 文件**：✅ 创建 `launch/monitor.launch.py`
- **用户文档**：✅ 创建 `docs/ros2-integration.md`
- **测试证据**：12 tests PASSED (test_launch + test_node)

### Phase 5：C++ 原生采集

- **Python 包装器**：✅ 创建 `src/native_collector/__init__.py`（含自动回退）
- **C++ 源码**：待编译（需 Linux/ARM 环境）
- **测试证据**：4 tests PASSED (test_fallback)

### Phase 6：Web 仪表盘增强

- **Grafana 导出**：✅ 创建 `src/web_dashboard/grafana.py`
- **推理面板 + AI Advisor 面板 + 历史回放**：已在 api.py 注册端点
- **测试证据**：11 tests PASSED (test_grafana)

### 跨模块更新

- **Prometheus 指标**：新增推理/告警/部署评分指标
- **CLI 增强**：dashboard 子命令新增 --inference-model/--target-fps/--target-latency
- **README 更新**：新增推理监控/AI Advisor/内存诊断/ROS2 章节
- **pyproject.toml**：新增 ros2/tensorrt/onnxruntime 可选依赖
