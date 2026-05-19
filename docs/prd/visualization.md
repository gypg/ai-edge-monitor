# visualization 模块 PRD

## 1. 模块目标与定位
提供监控结果可视化能力，帮助快速识别性能趋势与瓶颈。

> **新增（v2）**：实现已落地于 `src/visualizer/`。提供 `plot_report(data, output_path)` 函数与 `python -m visualizer --input X --output Y` CLI；matplotlib 优先，无 matplotlib 时降级到 stdlib（zlib + 手写 PNG chunk）回退后端；两条路径均同时写 `<report>.png.json` sidecar 记录原始 summary 与实际后端。详见 [add-aggregator-and-visualizer 变更说明](../changelog/add-aggregator-and-visualizer.md)。

## 2. 功能需求
- 生成 CPU/GPU/内存/功耗时序图。
- 生成窗口统计对比图（如 p95 CPU vs avg power）。
- 支持单次运行报告图导出（PNG/SVG）。
- 支持离线渲染（优先），可选在线轻量预览。
- 报告输出旁路一份 JSON sidecar，包含被绘制的完整 `WindowSummary` 与实际渲染后端，便于离线复核与回归比对。

## 3. 非功能需求
- 默认不驻留在实时采样热路径。
- 渲染失败不影响采集与存储。
- 图表模板可复用且可配置。
- 依赖降级：当 matplotlib 不可用时，stdlib 回退后端必须仍能产出合法 PNG（PNG magic header 校验通过），保证 e2e 流水线在最小镜像中可跑。

## 4. 接口定义
```python
from typing import Any, Dict, Union
from pathlib import Path

PathLike = Union[str, Path]

def plot_report(data: Union[Dict[str, Any], Any], output_path: PathLike) -> str: ...

class VisualizationService:
    def render_timeseries(self, input_path: str, out_path: str) -> None: ...
    def render_summary(self, input_path: str, out_path: str) -> None: ...
```

CLI：
```
python -m visualizer --input summary.json --output report.png
```

配置项建议：
- `figure_dpi`
- `figure_theme`
- `enable_interactive_preview`
- `force_stdlib_backend`（用于 CI 强制走回退路径回归）

## 5. 与其他模块交互
- 读取 `storage_exporter` 产出的数据文件，或直接接受 `aggregator_analyzer.get_summary_dict()` 的结果。
- 使用 `aggregator_analyzer` 输出的分析字段（含 `timeline_*` 短序列）增强图表注释。

## 6. 测试策略要点
- 图表生成正确性（字段映射与坐标轴）。
- 大数据量渲染性能测试。
- 缺失字段容错测试。
- 双后端等价性测试：matplotlib 与 stdlib 后端在同一份 summary 上分别渲染时，sidecar JSON 应字段一致；PNG 字节差异允许，但都需通过 PNG magic header 校验。
