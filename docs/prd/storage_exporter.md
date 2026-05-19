# storage_exporter 模块 PRD

## 1. 模块目标与定位
将采样与分析结果以低开销方式持久化，支撑离线分析与可追溯。

## 2. 功能需求
- 支持 `MetricSnapshot` 与 `AnalysisFrame` 输出。
- 支持 CSV/JSONL 格式。
- 支持缓冲批量写入与定时 flush。
- 支持文件轮转（按大小/时间）与磁盘配额控制。

## 3. 非功能需求
- 不阻塞采样主线程（建议队列+后台写入）。
- 写入失败可重试，超阈值后降级（仅内存缓存或丢弃最旧数据）。
- 资源占用可配置并有上限。

## 4. 接口定义
```python
class StorageExporter:
    def start(self) -> None: ...
    def write_snapshot(self, snapshot: object) -> None: ...
    def write_analysis(self, frame: object) -> None: ...
    def flush(self) -> None: ...
    def stop(self) -> None: ...
```

配置项建议：
- `output_dir`
- `output_format`
- `flush_interval_ms`
- `max_file_mb`
- `max_disk_usage_mb`

## 5. 与其他模块交互
- 接收 `sampler_scheduler` 原始快照与 `aggregator_analyzer` 分析帧。
- 与 `runtime_guardian` 协同处理写入积压与磁盘压力。

## 6. 测试策略要点
- 高吞吐写入稳定性测试。
- 磁盘满/权限不足异常恢复测试。
- 文件轮转与数据完整性测试。
