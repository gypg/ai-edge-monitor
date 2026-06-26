# 主规格文档 — AI Edge Monitor v2.0

> 本文档定义项目的目标、架构演进路线和阶段规划。
> 所有子代理在实现前必须阅读本文档和对应的子规格。

---

## 1. 项目目标

将 ai-edge-monitor 从"硬件监控工具"升级为"AI 部署助手"，覆盖嵌入式 AI 工程师的 5 大核心能力维度：

| 维度 | 当前评分 | 目标评分 | 对应子规格 |
|------|----------|----------|------------|
| ① C++ 基础 + 交叉编译 | 0/5 | 4/5 | `native-collector.md` |
| ② 中间件 ROS/pipeline | 1/5 | 4/5 | `ros2-bridge.md` |
| ③ 模型部署/推理框架 | 2/5 | 5/5 | `inference-integration.md` |
| ④ 性能优化 | 3/5 | 5/5 | `inference-integration.md` + `native-collector.md` |
| ⑤ 问题排查 | 3/5 | 5/5 | `memory-leak-detection.md` |
| ⑥ AI 工具化 | 2/5 | 4/5 | `ai-advisor.md` |
| ⑦ 可视化 | 2/5 | 4/5 | `web-dashboard.md` |

**总分目标**：11/30 → 30/35（加权后 ≥ 28/35）

---

## 2. 架构演进

### 2.1 当前架构（v1.x）

```
PlatformProbe ──→ Collector ──→ AggregatorAnalyzer ──→ StorageExporter / Visualizer
PowerSource  ──↗                                              ↓
                                                JSONL / CSV / summary.json / PNG
```

### 2.2 目标架构（v2.0）

```
┌─────────────────────────────────────────────────────────────┐
│                    AI Edge Monitor v2.0                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   │
│  │ C++ Native   │   │ ROS2 Bridge  │   │ Inference    │   │
│  │ Collector    │   │ Node         │   │ Monitor      │   │
│  │ (NEON/procfs)│   │ (pub/sub)    │   │ (TRT/ONNX)   │   │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘   │
│         │                  │                   │            │
│         ▼                  ▼                   ▼            │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              AggregatorAnalyzer (Python)              │   │
│  │    + DataQualityProcessor + AlertManager             │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         │                                   │
│         ┌───────────────┼───────────────┐                  │
│         ▼               ▼               ▼                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐              │
│  │ AI       │   │ Web      │   │ Memory   │              │
│  │ Advisor  │   │Dashboard │   │ Leak     │              │
│  │          │   │(+ Grafana)│   │ Detector │              │
│  └──────────┘   └──────────┘   └──────────┘              │
│                                                             │
│  RuntimeGuardian ← 监控所有组件自身开销                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 阶段规划

### Phase 1：推理框架集成（优先级最高，投入产出比最大）

**目标**：实际对接 TensorRT / ONNX Runtime，自动关联推理延迟与硬件指标

| 任务 | 子规格 | 估时 |
|------|--------|------|
| InferenceMonitor 上下文管理器 | `inference-integration.md` §2 | 4h |
| TensorRT Profiler 集成 | `inference-integration.md` §3 | 3h |
| ONNX Runtime Profiling 集成 | `inference-integration.md` §4 | 3h |
| 部署就绪评分 | `inference-integration.md` §5 | 2h |
| 推理性能基准测试 | `inference-integration.md` §6 | 2h |

**产出**：`src/inference_monitor/` 模块 + 测试 + 示例

### Phase 2：AI Advisor 自动诊断

**目标**：基于指标模式自动识别瓶颈并给出优化建议

| 任务 | 子规格 | 估时 |
|------|--------|------|
| 指标模式识别引擎 | `ai-advisor.md` §2 | 4h |
| 诊断规则库 | `ai-advisor.md` §3 | 3h |
| 优化建议生成器 | `ai-advisor.md` §4 | 2h |
| 部署就绪评估 | `ai-advisor.md` §5 | 2h |

**产出**：`src/ai_advisor/` 模块 + 测试

### Phase 3：内存泄漏检测与崩溃诊断

**目标**：检测目标推理进程的内存泄漏，抓取崩溃诊断信息

| 任务 | 子规格 | 估时 |
|------|--------|------|
| RSS 线性增长检测 | `memory-leak-detection.md` §2 | 3h |
| GPU 内存泄漏关联 | `memory-leak-detection.md` §3 | 2h |
| Debug Bundle 生成 | `memory-leak-detection.md` §4 | 3h |
| 信号处理器包装 | `memory-leak-detection.md` §5 | 2h |

**产出**：`src/memory_diagnostics/` 模块 + 测试

### Phase 4：ROS2 桥接

**目标**：作为 ROS2 节点发布监控数据，与机器人栈集成

| 任务 | 子规格 | 估时 |
|------|--------|------|
| ROS2 节点实现 | `ros2-bridge.md` §2 | 4h |
| 消息类型定义 | `ros2-bridge.md` §3 | 2h |
| Launch 文件 | `ros2-bridge.md` §4 | 1h |
| 推理管线监控 Topic | `ros2-bridge.md` §5 | 3h |

**产出**：`src/ros2_bridge/` 模块 + launch 文件

### Phase 5：C++ 原生采集守护进程

**目标**：用 C++ 实现零依赖的高性能指标采集，支持交叉编译

| 任务 | 子规格 | 估时 |
|------|--------|------|
| C++ 采集核心 | `native-collector.md` §2 | 6h |
| pybind11 桥接 | `native-collector.md` §3 | 3h |
| CMake + 交叉编译工具链 | `native-collector.md` §4 | 3h |
| 性能对比测试 | `native-collector.md` §5 | 2h |

**产出**：`native/` 目录 + CMakeLists.txt + 工具链文件

### Phase 6：Web 仪表盘增强

**目标**：增强现有仪表盘，添加 Grafana 导出和推理专属面板

| 任务 | 子规格 | 估时 |
|------|--------|------|
| 推理性能面板 | `web-dashboard.md` §2 | 3h |
| AI Advisor 诊断面板 | `web-dashboard.md` §3 | 2h |
| Grafana Dashboard JSON 导出 | `web-dashboard.md` §4 | 2h |
| 历史数据回放 | `web-dashboard.md` §5 | 2h |

**产出**：增强 `src/web_dashboard/` + Grafana JSON

---

## 4. 技术决策记录

| 决策 | 理由 |
|------|------|
| 核心保持 Python | 探针/分析/导出逻辑复杂度低，Python 开发效率高 |
| C++ 仅用于采集热路径 | `/proc` 读取 + NEON 统计计算是唯一需要原生性能的地方 |
| ROS2 而非 ROS1 | ROS2 是当前主流，DDS 支持实时性 |
| Web 仪表盘用 stdlib HTTP | 避免引入 Flask/FastAPI 等重型框架，适合边缘设备 |
| Chart.js 而非 D3/ECharts | CDN 加载，零构建步骤，轻量化 |
| 推理框架仅可选依赖 | 不是所有设备都有 TensorRT，通过 try/except 降级 |
