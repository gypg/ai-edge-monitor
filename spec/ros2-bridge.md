# 子规格 — ROS2 桥接

> 关联验收标准：`acceptance-criteria.md` Phase 4

---

## 1. 概述

创建 `src/ros2_bridge/` 模块，将监控数据发布为 ROS2 Topic，支持与机器人栈集成。

---

## 2. ROS2 节点实现

### 2.1 节点结构

```python
class MonitorNode(Node):
    """ROS2 节点：发布系统监控和推理指标。"""

    def __init__(self, config: MonitorConfig) -> None: ...

    # 系统指标 Publishers
    # /system/cpu_percent      std_msgs/Float64
    # /system/memory_mb        std_msgs/Float64
    # /system/power_watt       std_msgs/Float64
    # /system/temperature_c    std_msgs/Float64
    # /system/gpu_utilization  std_msgs/Float64

    # 推理指标 Publishers
    # /inference/fps           std_msgs/Float64
    # /inference/latency_p95   std_msgs/Float64
    # /inference/gpu_util      std_msgs/Float64

    # 综合状态 Publisher
    # /monitor/status          std_msgs/String (JSON)
```

### 2.2 发布频率

- 与采集间隔一致（默认 1000ms）
- 可通过 ROS2 parameter 覆盖：`ros2 run ai_edge_monitor monitor_node --ros-args -p publish_rate:=2.0`

---

## 3. 消息类型

### 3.1 标准消息（零依赖）

使用 `std_msgs` 包的内置类型：
- `Float64` — 所有数值指标
- `String` — 综合状态（JSON 序列化）

### 3.2 自定义消息（可选，增强功能）

```msg
# MonitorMetrics.msg
builtin_interfaces/Time stamp
float64 cpu_percent
float64 memory_used_mb
float64 power_watt
float64 temperature_c
float64 gpu_utilization
float64 inference_fps
float64 inference_latency_p95
string probe_name
string power_source
```

---

## 4. Launch 文件

```python
# launch/monitor.launch.py
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='ai_edge_monitor',
            executable='monitor_node',
            name='ai_edge_monitor',
            parameters=[{
                'publish_rate': 1.0,
                'power_source': 'auto',
                'include_inference': True,
            }],
            output='screen',
        ),
    ])
```

---

## 5. 推理管线监控 Topic

当与 `InferenceMonitor` 集成时，自动发布推理专属指标。

### 5.1 Topic 映射

| InferenceMonitor 字段 | ROS2 Topic | 消息类型 |
|----------------------|------------|----------|
| `fps` | `/inference/fps` | `Float64` |
| `latency_p95_ms` | `/inference/latency_p95` | `Float64` |
| `gpu_util_avg` | `/inference/gpu_util` | `Float64` |
| `power_avg_watt` | `/inference/power` | `Float64` |

---

## 6. 降级策略

```python
try:
    import rclpy
    from rclpy.node import Node
    HAS_ROS2 = True
except ImportError:
    HAS_ROS2 = False
```

无 ROS2 时：
- `MonitorNode` 不可实例化
- `create_monitor_node()` 返回 `None` + 日志 WARNING
- 其余功能（CLI、Web Dashboard）不受影响

---

## 7. 测试策略

| 测试类型 | 位置 | 说明 |
|----------|------|------|
| 单元测试 | `tests/ros2_bridge/test_node.py` | Mock rclpy，验证 Topic 创建和消息发布 |
| 集成测试 | `tests/ros2_bridge/test_integration.py` | Mock Collector → MonitorNode 数据流 |
| 降级测试 | `tests/ros2_bridge/test_fallback.py` | 无 rclpy 环境下验证优雅降级 |
