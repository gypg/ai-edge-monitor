# ai_edge_monitor -- ROS2 Bridge

This directory contains the ROS2 package definition for the
`ai_edge_monitor` bridge node. The node publishes real-time system and
inference monitoring metrics as standard ROS2 topics.

## Prerequisites

- ROS 2 Humble (or later) sourced in your shell
- The `ai-edge-monitor` Python package installed (editable mode is fine)

```bash
source /opt/ros/humble/setup.bash   # adjust distro as needed
pip install -e /path/to/ai-embedded-hw-monitoring
```

## Building

The package uses `ament_python` (pure-Python build type), so no CMake
compilation step is needed:

```bash
cd ros2/
colcon build --packages-select ai_edge_monitor
source install/setup.bash
```

## Launching

```bash
# Default 1 Hz publish rate
ros2 launch ai_edge_monitor monitor.launch.py

# Custom rate (10 Hz) and node name
ros2 launch ai_edge_monitor monitor.launch.py \
    publish_rate:=10.0 node_name:=my_monitor
```

### Launch Arguments

| Argument       | Default             | Description                     |
|----------------|---------------------|---------------------------------|
| `publish_rate` | `1.0`               | Publishing frequency in Hz      |
| `node_name`    | `ai_edge_monitor`   | ROS2 node name                  |

## Published Topics

### System Metrics (`std_msgs/Float64`)

| Topic                    | Key              | Description                  |
|--------------------------|------------------|------------------------------|
| `/system/cpu_percent`    | `cpu_percent`    | CPU utilisation (%)          |
| `/system/memory_mb`      | `memory_mb`      | Memory used (MB)             |
| `/system/power_watt`     | `power_watt`     | Power draw (W)               |
| `/system/temperature_c`  | `temperature_c`  | Temperature (degrees C)      |
| `/system/gpu_utilization`| `gpu_utilization`| GPU utilisation (%)          |

### Inference Metrics (`std_msgs/Float64`)

| Topic                    | Key            | Description                  |
|--------------------------|----------------|------------------------------|
| `/inference/fps`         | `fps`          | Frames per second            |
| `/inference/latency_p95` | `latency_p95`  | 95th-percentile latency (ms) |
| `/inference/gpu_util`    | `gpu_util`     | Inference GPU usage (%)      |

### Status (`std_msgs/String`)

| Topic               | Description                         |
|---------------------|-------------------------------------|
| `/monitor/status`   | JSON-encoded full status dictionary |

## Subscribing from the Command Line

```bash
# Echo CPU usage
ros2 topic echo /system/cpu_percent

# Check publishing rate
ros2 topic hz /inference/fps

# List all published topics
ros2 topic list | grep -E 'system|inference|monitor'
```

## Running Tests (without ROS2)

All tests mock `rclpy` and run on any machine:

```bash
python tests/ros2_bridge/test_launch.py
python tests/ros2_bridge/test_node.py
python tests/ros2_bridge/test_node_extended.py
```

## Architecture

```
AggregatorAnalyzer.get_summary_dict()
        |
        v
  MonitorNode.publish_metrics(summary)   --> /system/* topics
  MonitorNode.publish_inference(results)  --> /inference/* topics
  MonitorNode.publish_status(dict)        --> /monitor/status (JSON)
```

The `MonitorNode` gracefully degrades to no-ops when `rclpy` is not
installed, so the monitoring pipeline works on machines without ROS 2.
