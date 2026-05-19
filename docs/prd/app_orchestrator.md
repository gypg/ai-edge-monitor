# app_orchestrator 模块 PRD

## 1. 模块目标与定位
作为系统入口与生命周期管理器，负责组装各模块并协调运行。

## 2. 功能需求
- CLI 参数解析与运行模式选择（实时监控/离线报告）。
- 模块初始化顺序控制与依赖注入。
- 启停流程管理（start/stop/graceful shutdown）。
- 运行总结输出（时长、样本量、异常次数、降级次数）。

## 3. 非功能需求
- 启动失败时可安全退出并给出可诊断日志。
- 停止时保证关键缓冲 flush。
- 编排层保持轻量，不做重计算。

## 4. 接口定义
```python
class AppOrchestrator:
    def bootstrap(self, config_path: str | None, cli_args: dict) -> None: ...
    def run(self) -> int: ...
    def shutdown(self) -> None: ...


def main() -> int: ...
```

CLI 示例：
- `python -m monitor.main --config ./config.yaml --duration 300`
- `python -m monitor.main --no-gpu --output ./out`

## 5. 与其他模块交互
- 从 `config_manager` 获取有效配置。
- 依次启动 `platform_adapter`、`metrics_collector`、`sampler_scheduler`、`storage_exporter`、`runtime_guardian`。
- 在退出阶段调用 `flush`、`stop`、`close`。

## 6. 测试策略要点
- 启停生命周期测试。
- 异常注入测试（单模块启动失败、运行中断）。
- CLI 参数覆盖配置的集成测试。
