# CHANGELOG

## [2.0.0] - 2026-06-28

### Added
- 新增 `src/platform_adapter/jetson_probe.py`，通过 jtop / tegrastats 读取 Jetson GPU 与功耗指标。
- 新增 `src/power_monitor/jetson_source.py`，作为 Jetson 平台专用功耗数据源。
- `select_default_probe` 自动组合 `NvidiaSmiProbe` 与 `JetsonProbe`。
- `select_default_source` 默认优先序改为 `("sysfs", "jetson")`。
- 新增 `tests/platform_adapter/test_jetson_probe.py` 与 `tests/power_monitor/test_jetson_source.py` 单元测试。
- 新增 `docs/dashboard.html` 独立看板页面，可连接本地 `http://localhost:17429` 查看实时指标。
- Dockerfile 默认暴露 17429 端口并启动 Web 仪表盘。
- README 新增中英双语项目介绍。

### Changed
- Web 仪表盘默认端口从 `8080` 改为 `17429`，避免与常见服务冲突。
- `SysfsPowerSource` 支持 `device_name` 参数，可指定优先读取的电源设备。
- README Quick Demo 恢复为本地命令行方式。

### Fixed
- `src/memory_diagnostics/debug_bundle.py` 中 `generation_time_ms` 在 Windows 上可能为 0 的问题。
- 删除内容已合并到 main 的遗留工作分支 `worktree-phase-a-cli-exporter` 和 `worktree-phase-c-observability`。
