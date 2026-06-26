# ROS2 Integration Guide

This guide covers running `ai-edge-monitor` as a ROS2 node so that system
and inference metrics are published as standard ROS2 topics.

---

## Prerequisites

| Requirement | Minimum version | Notes |
|-------------|-----------------|-------|
| ROS 2 | Humble (22.04) or later | Iron, Jazzy, and Rolling also supported |
| Python | 3.8+ | Must match your ROS 2 Python installation |
| colcon | Latest | Used to build the package inside a ROS 2 workspace |

Verify your ROS 2 installation:

```bash
# Source the ROS 2 setup script (adjust distro as needed)
source /opt/ros/humble/setup.bash

# Confirm the CLI is available
ros2 --help
```

---

## Installation

### Option A -- Standalone (development / testing)

```bash
pip install ai-edge-monitor
```

### Option B -- Inside a ROS 2 workspace

```bash
# Create or navigate to your workspace
mkdir -p ~/ros2_ws/src && cd ~/ros2_ws/src

# Clone the repository
git clone https://github.com/your-org/ai-embedded-hw-monitoring.git ai_edge_monitor

# Install Python dependencies
cd ~/ros2_ws
pip install -r src/ai_edge_monitor/requirements.txt

# Build (if using ament_cmake/colcon layout)
colcon build --packages-select ai_edge_monitor
source install/setup.bash
```

---

## Launch

The recommended way to start the monitor:

```bash
ros2 launch ai_edge_monitor monitor.launch.py
```

Override parameters at launch time:

```bash
ros2 launch ai_edge_monitor monitor.launch.py publish_rate:=2.0
```

Or run the node directly without a launch file:

```bash
ros2 run ai_edge_monitor monitor_node --ros-args \
    -p publish_rate:=2.0 \
    -p power_source:=nvidia-smi \
    -p include_inference:=false
```

---

## Published Topics

### System Metrics

| Topic | Message Type | Description |
|-------|-------------|-------------|
| `/system/cpu_percent` | `std_msgs/Float64` | CPU utilisation (%) |
| `/system/memory_mb` | `std_msgs/Float64` | Memory used (MB) |
| `/system/power_watt` | `std_msgs/Float64` | Power draw (W) |
| `/system/temperature_c` | `std_msgs/Float64` | SoC temperature (deg C) |
| `/system/gpu_utilization` | `std_msgs/Float64` | GPU utilisation (%) |

### Inference Metrics (optional)

| Topic | Message Type | Description |
|-------|-------------|-------------|
| `/inference/fps` | `std_msgs/Float64` | Inference frames per second |
| `/inference/latency_p95` | `std_msgs/Float64` | 95th-percentile latency (ms) |
| `/inference/gpu_util` | `std_msgs/Float64` | GPU utilisation during inference (%) |

### Aggregate Status

| Topic | Message Type | Description |
|-------|-------------|-------------|
| `/monitor/status` | `std_msgs/String` | JSON blob with all current metrics |

---

## Parameters

All parameters are set under the `ai_edge_monitor` node name.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `publish_rate` | `double` | `1.0` | Publishing frequency in Hz. Controls how often metrics are pushed to topics. |
| `power_source` | `string` | `"auto"` | Power probe strategy: `auto`, `nvidia-smi`, `jetson`, `rpi`, or `dummy`. |
| `include_inference` | `bool` | `true` | Whether to publish inference-pipeline topics. Set `false` if not running inference workloads. |

---

## Integration with an Existing ROS 2 Workspace

1. **Copy or symlink** the `launch/` directory into your workspace's share path
   so `ros2 launch` can find it.
2. **Source** the workspace overlay (`source install/setup.bash`) before launching.
3. **Remap topics** if names conflict with existing nodes:

   ```bash
   ros2 launch ai_edge_monitor monitor.launch.py \
       --ros-args -r /system/cpu_percent:=/my_robot/cpu
   ```

4. **Use with `robot_state_publisher` or `tf2`** -- the standard message types
   (`Float64`, `String`) integrate cleanly with any ROS 2 subscriber.

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'rclpy'`

ROS 2 Python packages are not on the current Python path. Make sure you have
sourced the ROS 2 setup file:

```bash
source /opt/ros/humble/setup.bash
```

### `No executable found` when running `ros2 run`

The package was not built or the install space was not sourced. Rebuild and
re-source:

```bash
colcon build --packages-select ai_edge_monitor
source install/setup.bash
```

### Node starts but no topics appear

Check that the node is running:

```bash
ros2 node list
ros2 node info /ai_edge_monitor
```

Verify that `publish_rate` is greater than 0 and that `include_inference` is
set as expected.

### Running without ROS 2 installed

The rest of `ai-edge-monitor` (CLI, web dashboard, exporters) works without
ROS 2. Only the `ros2_bridge` module requires `rclpy`. If `rclpy` is not
installed the monitor logs a warning and continues without ROS 2 publishing.
