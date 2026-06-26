# AGENTS.md — AI Edge Monitor 项目地图

> 本文件是 AI 子代理的"导航地图"。任何代理在修改代码前必须先读本文件，
> 理解项目定位、仓库结构和开发约束，避免盲目探索浪费 token。

---

## 项目定位

**ai-edge-monitor** 是面向 Jetson、Raspberry Pi、x86 边缘服务器的 **AI 部署助手**。

从"硬件监控工具"演进为"AI 部署助手"，不仅报告设备指标，还：
- 关联推理框架行为（TensorRT / ONNX Runtime / TFLite）
- 自动诊断性能瓶颈并给出优化建议
- 集成 ROS2 中间件，支持机器人全栈可观测
- 提供内存泄漏检测、崩溃诊断等调试能力
- 通过 Web 仪表盘实现实时可视化

**目标用户**：嵌入式 AI 视觉模型部署工程师（3+ 年经验）
**核心价值**：用最低的 CPU 开销，实现最高的推理帧率和最低的延迟

---

## 仓库结构

```
ai-edge-monitor/
├── AGENTS.md                          # 本文件 — 代理导航地图
├── spec/                              # 规格文档（代理必读）
│   ├── main-spec.md                   # 主规格：目标、架构、阶段规划
│   ├── acceptance-criteria.md         # 验收标准：量化指标 + 判定方法
│   ├── inference-integration.md       # 推理框架集成规格
│   ├── ros2-bridge.md                 # ROS2 桥接规格
│   ├── ai-advisor.md                  # AI Advisor 自动诊断规格
│   ├── memory-leak-detection.md       # 内存泄漏检测规格
│   ├── native-collector.md            # C++ 原生采集守护进程规格
│   └── web-dashboard.md               # Web 仪表盘增强规格
├── src/                               # 源代码
│   ├── aggregator_analyzer/           # 跨源聚合与时间窗口分析
│   ├── alert_manager/                 # 告警引擎（阈值/趋势/异常）
│   ├── app_orchestrator/              # 应用编排入口
│   ├── cli/                           # CLI 入口（run/report/scenario/dashboard）
│   ├── collector/                     # 双路采集生命周期管理
│   ├── config_manager/                # YAML 配置 + 环境变量 + CLI 覆盖
│   ├── data_quality/                  # 数据质量处理（缺失值/异常值）
│   ├── platform_adapter/              # 跨平台硬件探针
│   ├── power_monitor/                 # 功耗采集与滑窗统计
│   ├── prometheus_exporter/           # Prometheus 指标暴露
│   ├── runtime_guardian/              # 自监控与降级/熔断
│   ├── scenarios/                     # 合成场景生成器
│   ├── scheduler/                     # 周期调度与降级管理
│   ├── storage_exporter/              # JSONL/CSV/summary 导出
│   ├── system_monitor/                # 网络/磁盘 I/O 扩展监控
│   ├── visualizer/                    # 报告渲染（matplotlib + stdlib PNG）
│   └── web_dashboard/                 # Web 实时仪表盘
├── tests/                             # 单元测试
├── integration/                       # 集成测试
├── examples/                          # 示例脚本
├── tools/                             # 工具脚本（性能基准等）
├── docs/                              # 文档（PRD/变更日志/兼容矩阵）
└── pyproject.toml                     # 项目配置
```

---

## 模块依赖关系

```
CLI → Orchestrator → Collector → PlatformSampler + PowerSampler
                         ↓
                  AggregatorAnalyzer ←── DataQualityProcessor
                         ↓
              ┌──────────┼──────────┐
              ↓          ↓          ↓
        StorageExporter  Visualizer  PrometheusExporter
              ↓                    ↓
         JSONL/CSV/JSON        /metrics endpoint

RuntimeGuardian ← 监控以上所有模块的自身开销
AlertManager    ← 消费 AggregatorAnalyzer 的指标数据
WebDashboard    ← 聚合所有模块的实时数据
```

---

## 开发约束（代理必须遵守）

### 代码风格
- Python 3.8+ 兼容（不使用 3.10+ 语法如 `match/case`、`X | Y` 类型联合）
- 所有公共函数必须有类型注解
- 不可变模式优先：创建新对象，不修改传入参数
- 单文件 ≤ 800 行，单函数 ≤ 50 行
- 模块边界通过 `__init__.py` 控制公开 API

### 依赖策略
- 核心库零硬依赖（Python stdlib only）
- 可选依赖通过 `try/except ImportError` 优雅降级
- 新增第三方依赖必须在 `pyproject.toml` 的 extras 中声明

### 测试要求
- 每个新模块必须有对应 `tests/<module>/test_baseline.py`
- 基线测试验证：CPU 增量 < 0.05ms，RSS 增量 < 0.05MB（30s × 100ms 空跑）
- 集成测试验证模块间交互
- 所有测试必须在无 GPU、无 psutil 的环境下通过（dummy 回退）

### 线程安全
- 所有共享状态必须通过 `threading.Lock` 保护
- 探针的 `read_metrics()` 永远不抛异常（返回 `status != "ok"`）
- 后台线程必须设为 daemon 模式

### 提交规范
- 格式：`<type>: <description>`（feat / fix / refactor / docs / test / perf）
- 每次提交聚焦单一变更
- 不包含 AI 工具的署名信息

---

## 代理分工模式

| 角色 | 职责 | 触发条件 |
|------|------|----------|
| `planner` | 拆分任务、创建实现计划 | 收到新功能需求 |
| `code-reviewer` | 审查代码质量、安全、性能 | 代码修改完成后 |
| `python-reviewer` | Python 专项审查（PEP 8、类型注解） | Python 代码变更 |
| `security-reviewer` | 安全审计 | 涉及输入处理/网络/认证 |
| `tdd-guide` | 强制 TDD 流程（RED→GREEN→IMPROVE） | 新功能/bug 修复 |
| `build-error-resolver` | 修复构建/类型错误 | CI 失败 |

### 工作流
1. 代理读取 `AGENTS.md` 了解项目
2. 代理读取 `spec/` 下相关规格文档
3. 代理按规格实现，不擅自扩展范围
4. 实现完成后，`code-reviewer` 审查
5. 审查通过后，运行测试提供通过证据
6. 所有证据写入 `spec/acceptance-criteria.md` 对应条目
