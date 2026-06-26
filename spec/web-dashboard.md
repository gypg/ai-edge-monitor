# 子规格 — Web 仪表盘增强

> 关联验收标准：`acceptance-criteria.md` Phase 6

---

## 1. 概述

增强现有 `src/web_dashboard/` 模块，添加：
- 推理性能专属面板（FPS/延迟直方图）
- AI Advisor 诊断面板
- Grafana Dashboard JSON 导出
- 历史数据回放功能

---

## 2. 推理性能面板

### 2.1 新增 API 端点

```
GET /api/inference
```

响应：
```json
{
    "fps": 30.5,
    "latency_p50_ms": 12.3,
    "latency_p95_ms": 18.7,
    "latency_p99_ms": 25.1,
    "frame_count": 1000,
    "gpu_util_during_inference": 85.2,
    "power_during_inference": 12.5,
    "timeline_fps": [30.1, 30.5, 30.3, ...],
    "timeline_latency_p95": [18.2, 18.7, 19.1, ...],
    "ts_ms": 1700000000000
}
```

### 2.2 前端组件

- **FPS 实时折线图**：绿色（达标）/ 黄色（临界）/ 红色（不达标）
- **延迟分布直方图**：P50/P95/P99 三档柱状图
- **推理吞吐量仪表盘**：大字显示当前 FPS

### 2.3 阈值配置

从 `config.thresholds` 读取：
- `target_fps`：目标 FPS（默认 30）
- `target_latency_ms`：目标延迟（默认 33ms）

---

## 3. AI Advisor 诊断面板

### 3.1 新增 API 端点

```
GET /api/diagnosis
```

响应：
```json
{
    "diagnoses": [
        {
            "category": "thermal",
            "priority": "high",
            "suggestion": "温度偏高，建议监控散热状况",
            "evidence": "当前温度 72.5°C，超过 70°C 阈值"
        }
    ],
    "deployment_score": {
        "total": 78,
        "verdict": "marginal",
        "bottlenecks": ["thermal"]
    },
    "ts_ms": 1700000000000
}
```

### 3.2 前端组件

- **诊断卡片列表**：按优先级排序，颜色编码
  - CRITICAL：红色背景
  - HIGH：橙色背景
  - MEDIUM：黄色背景
  - LOW：蓝色背景
- **部署就绪评分**：大字显示 0-100 分，环形进度条
- **瓶颈标签**：显示识别到的瓶颈类型

---

## 4. Grafana Dashboard JSON 导出

### 4.1 API 端点

```
GET /api/grafana-dashboard
```

返回可直接导入 Grafana 的 Dashboard JSON。

### 4.2 Dashboard 面板

| 面板 | 数据源 | 类型 |
|------|--------|------|
| CPU Usage | `ai_edge_cpu_percent` | Gauge + Time Series |
| Memory Usage | `ai_edge_memory_used_bytes` | Gauge + Time Series |
| Power Draw | `ai_edge_power_watts` | Gauge + Time Series |
| Temperature | `ai_edge_temperature_celsius` | Gauge + Time Series |
| Inference FPS | `ai_edge_inference_fps` | Time Series |
| Inference Latency | `ai_edge_inference_latency_p95` | Time Series |
| Active Alerts | `ai_edge_active_alerts` | Stat |

### 4.3 数据源

默认配置 Prometheus 数据源，指向当前监控实例的 `/metrics` 端点。

---

## 5. 历史数据回放

### 5.1 API 端点

```
GET /api/history?from=<ts_ms>&to=<ts_ms>&limit=1000
```

读取 JSONL 历史文件，返回指定时间范围内的数据。

### 5.2 前端功能

- 时间范围选择器（滑块）
- 回放速度控制（1x / 2x / 5x / 10x）
- 暂停/继续按钮

### 5.3 约束

- 最多加载 10000 个数据点（防止浏览器内存溢出）
- 超过限制时自动降采样

---

## 6. 测试策略

| 测试类型 | 位置 | 说明 |
|----------|------|------|
| API 单元测试 | `tests/web_dashboard/test_api.py` | 验证所有端点返回正确结构 |
| Grafana JSON 测试 | `tests/web_dashboard/test_grafana.py` | 验证 JSON 结构可导入 |
| 前端手动测试 | — | 浏览器中验证图表渲染 |
| 性能测试 | `tests/web_dashboard/test_overhead.py` | 仪表盘服务不增加 > 1% CPU 开销 |
