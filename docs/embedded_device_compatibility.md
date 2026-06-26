# 嵌入式设备兼容矩阵

本文档详细说明 `ai-edge-monitor` 对各类嵌入式设备的支持情况。

## 支持的设备平台

### 1. NVIDIA Jetson 系列

| 设备型号 | CPU 监控 | 内存监控 | GPU 监控 | 温度监控 | 功耗监控 | 状态 |
|---------|----------|----------|----------|----------|----------|------|
| Jetson Nano | ✅ | ✅ | ✅ | ✅ | ✅ | 完全支持 |
| Jetson TX2 | ✅ | ✅ | ✅ | ✅ | ✅ | 完全支持 |
| Jetson Xavier | ✅ | ✅ | ✅ | ✅ | ✅ | 完全支持 |
| Jetson Orin | ✅ | ✅ | ✅ | ✅ | ✅ | 完全支持 |

**特性说明：**
- 使用 `nvidia-smi` 监控 GPU 利用率和显存
- 支持 Tegra 特定的温度传感器
- 支持 `/sys/class/power_supply` 功耗监控
- 自动检测 CUDA/TensorRT 能力

### 2. Raspberry Pi 系列

| 设备型号 | CPU 监控 | 内存监控 | GPU 监控 | 温度监控 | 功耗监控 | 状态 |
|---------|----------|----------|----------|----------|----------|------|
| Raspberry Pi 3B+ | ✅ | ✅ | ❌ | ✅ | ❌ | 基本支持 |
| Raspberry Pi 4B | ✅ | ✅ | ✅ | ✅ | ❌ | 完全支持 |
| Raspberry Pi 5 | ✅ | ✅ | ✅ | ✅ | ❌ | 完全支持 |

**特性说明：**
- 使用 `vcgencmd` 监控 GPU 内存
- 支持 `/sys/class/thermal` 温度监控
- 支持 GPIO 和摄像头能力检测
- 无内置功耗监控（需外部硬件）

### 3. 通用 Linux 边缘设备

| 设备类型 | CPU 监控 | 内存监控 | GPU 监控 | 温度监控 | 功耗监控 | 状态 |
|---------|----------|----------|----------|----------|----------|------|
| x86 边缘服务器 | ✅ | ✅ | ✅ | ✅ | ✅ | 完全支持 |
| ARM 边缘设备 | ✅ | ✅ | ❌ | ✅ | ✅ | 基本支持 |

**特性说明：**
- 使用 `/proc/stat` 和 `/proc/meminfo` 监控 CPU 和内存
- 支持 NVIDIA GPU（通过 `nvidia-smi`）
- 支持 `/sys/class/thermal` 温度监控
- 支持 `/sys/class/power_supply` 功耗监控

## 探测器优先级

系统会自动检测并选择最佳探测器，优先级如下：

1. **EmbeddedProbe** - 专用嵌入式设备探测器（Jetson/Raspberry Pi）
2. **ProcfsProbe** - Linux 通用探测器
3. **PsutilProbe** - 跨平台探测器（需要 psutil）
4. **DummyProbe** - 虚拟探测器（用于测试）

## GPU 监控能力

### Jetson 设备
- **nvidia-smi**: 支持 GPU 利用率、显存使用、温度
- **CUDA**: 自动检测 CUDA 能力
- **TensorRT**: 自动检测 TensorRT 支持

### Raspberry Pi 设备
- **vcgencmd**: 支持 GPU 内存监控
- **VideoCore**: 支持 VideoCore GPU 信息

### 通用 NVIDIA GPU
- **nvidia-smi**: 支持 GPU 利用率、显存使用、温度
- **自动组合**: 与 CPU 探测器自动组合

## 温度监控

### 支持的传感器路径
- `/sys/class/thermal/thermal_zone*/temp`
- `/sys/class/thermal/cooling_device*/temp`

### 设备特定温度源
- **Jetson**: Tegra 温度传感器
- **Raspberry Pi**: CPU 温度传感器
- **通用 Linux**: 系统温度传感器

## 功耗监控

### Jetson 设备
- **sysfs**: `/sys/class/power_supply/*`
- **INA3221**: 三通道电流/电压监测
- **功耗范围**: 5W - 30W（取决于型号）

### Raspberry Pi 设备
- **无内置功耗监控**
- **外部硬件**: 需要 INA219/INA226 等传感器
- **软件估算**: 基于 CPU 使用率的功耗估算

### 通用 Linux 设备
- **sysfs**: `/sys/class/power_supply/*`
- **ACPI**: 笔记本电池监控
- **IPMI**: 服务器功耗监控

## 性能基准

### 采样开销

| 设备类型 | CPU 开销 | 内存开销 | 采样延迟 |
|---------|----------|----------|----------|
| Jetson Nano | < 1ms | < 1MB | < 5ms |
| Jetson Xavier | < 0.5ms | < 1MB | < 2ms |
| Raspberry Pi 4B | < 2ms | < 1MB | < 10ms |
| x86 边缘服务器 | < 0.1ms | < 1MB | < 1ms |

### 采样频率建议

| 设备类型 | 推荐频率 | 最大频率 |
|---------|----------|----------|
| Jetson Nano | 500ms | 100ms |
| Jetson Xavier | 200ms | 50ms |
| Raspberry Pi 4B | 1000ms | 200ms |
| x86 边缘服务器 | 100ms | 10ms |

## 配置示例

### Jetson 设备配置

```yaml
# monitor_jetson.yaml
duration_sec: 300
interval_ms: 500
output_dir: reports/jetson
device: jetson
force_dummy: false
exporters:
  - jsonl
  - csv
  - summary
  - png
thresholds:
  cpu_high: 80
  gpu_high: 90
  temp_high: 85
```

### Raspberry Pi 配置

```yaml
# monitor_rpi.yaml
duration_sec: 300
interval_ms: 1000
output_dir: reports/rpi
device: rpi
force_dummy: false
exporters:
  - jsonl
  - csv
  - summary
  - png
thresholds:
  cpu_high: 80
  temp_high: 75
```

### 通用 Linux 配置

```yaml
# monitor_linux.yaml
duration_sec: 300
interval_ms: 200
output_dir: reports/linux
device: auto
force_dummy: false
exporters:
  - jsonl
  - csv
  - summary
  - png
thresholds:
  cpu_high: 85
  gpu_high: 90
  temp_high: 80
```

## 故障排除

### Jetson 设备

**问题**: GPU 监控不可用
```
解决方案:
1. 检查 nvidia-smi 是否安装: nvidia-smi --version
2. 检查 CUDA 是否安装: nvcc --version
3. 检查权限: sudo usermod -aG video $USER
```

**问题**: 温度监控失败
```
解决方案:
1. 检查温度传感器: ls /sys/class/thermal/
2. 检查权限: sudo chmod 644 /sys/class/thermal/thermal_zone*/temp
3. 使用 jtop 工具: sudo pip install jetson-stats
```

### Raspberry Pi 设备

**问题**: GPU 监控不可用
```
解决方案:
1. 检查 vcgencmd: vcgencmd version
2. 检查 GPU 内存分配: vcgencmd get_mem gpu
3. 在 /boot/config.txt 中设置 gpu_mem=128
```

**问题**: 温度过高
```
解决方案:
1. 添加散热片或风扇
2. 降低 CPU 频率: echo "performance" | sudo tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
3. 监控温度: watch -n 1 vcgencmd measure_temp
```

## 扩展支持

### 添加新设备支持

1. **创建探测器**: 继承 `PlatformProbe` 类
2. **实现检测逻辑**: 在 `_detect_device()` 中添加设备检测
3. **实现指标读取**: 在 `read_metrics()` 中实现指标读取
4. **更新优先级**: 在 `select_default_probe()` 中添加新探测器

### 自定义阈值

```python
from config_manager import MonitorConfig

config = MonitorConfig(
    duration_sec=300,
    interval_ms=500,
    thresholds={
        "cpu_high": 80,
        "gpu_high": 90,
        "temp_high": 85,
        "power_high": 25.0,  # 功耗阈值（瓦特）
    }
)
```

## 最佳实践

### 1. 采样频率选择
- **开发阶段**: 使用较高频率（100-500ms）进行详细分析
- **生产环境**: 使用较低频率（1-5s）减少开销
- **长时间监控**: 使用最低频率（5-10s）节省资源

### 2. 阈值设置
- **CPU**: 根据设备性能设置（Jetson: 80%, RPi: 70%）
- **温度**: 根据散热条件设置（Jetson: 85°C, RPi: 75°C）
- **功耗**: 根据电源容量设置（Jetson: 25W, RPi: 15W）

### 3. 数据导出
- **实时分析**: 使用 JSONL 格式
- **离线分析**: 使用 CSV 格式
- **报告生成**: 使用 PNG + JSON sidecar

### 4. 告警配置
- **阈值告警**: 设置合理的告警阈值
- **趋势告警**: 监控指标变化趋势
- **异常检测**: 检测异常模式

## 参考资料

- [Jetson 技术文档](https://developer.nvidia.com/embedded-computing)
- [Raspberry Pi 文档](https://www.raspberrypi.com/documentation/)
- [Linux 性能监控](https://www.brendangregg.com/linuxperf.html)
- [ai-edge-monitor PRD](./prd/README.md)