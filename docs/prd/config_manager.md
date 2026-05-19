# config_manager 模块 PRD

## 1. 模块目标与定位
负责统一配置的加载、校验、合并与分发，确保不同部署环境下行为可控、可复现。

## 2. 功能需求
- 支持默认配置、YAML/JSON 文件配置、CLI 参数覆盖。
- 支持配置热更新（可选，默认关闭）。
- 对采样周期、缓冲区大小、开销阈值做边界校验。
- 输出标准化配置对象供全局使用。

## 3. 非功能需求
- 初始化耗时 < 100ms。
- 内存开销 < 2MB。
- 配置错误时提供明确错误信息并回退安全默认值（若允许）。
- 与平台无关，支持 Linux ARM/x86。

## 4. 接口定义
```python
from dataclasses import dataclass
from typing import Optional

@dataclass(slots=True)
class MonitorConfig:
    sample_interval_ms: int
    power_interval_ms: int
    buffer_size: int
    cpu_overhead_limit_pct: float
    memory_limit_mb: float
    output_dir: str
    output_format: str  # csv | jsonl
    enable_gpu: bool
    enable_power: bool
    device_id: str


def load_config(path: Optional[str], cli_overrides: dict) -> MonitorConfig: ...
def validate_config(cfg: MonitorConfig) -> None: ...
def dump_effective_config(cfg: MonitorConfig, out_path: str) -> None: ...
```

## 5. 与其他模块交互
- `app_orchestrator` 启动时调用 `load_config`。
- 向 `sampler_scheduler`、`runtime_guardian`、`storage_exporter` 分发配置。

## 6. 测试策略要点
- 参数边界测试（最小/最大采样周期）。
- 非法配置回退行为测试。
- 多来源配置优先级测试（CLI > 文件 > 默认）。
