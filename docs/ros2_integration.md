# ROS2 Integration Guide

This document describes how to use `ai-edge-monitor` as a ROS2 node, publish
hardware and inference metrics as standard ROS2 topics, and visualize them with
Foxglove Studio or RViz.

---

## 1. Overview

The `ros2_bridge` module wraps the monitoring pipeline inside a standard ROS2
node.  It reads aggregated metrics from `AggregatorAnalyzer.get_summary_dict()`
and inference results from `InferenceMonitor`, then publishes them as
`std_msgs/Float64` and `std_msgs/String` messages.

### Architecture

```
  +---------------------------------------------------------------+
  |                      ai-edge-monitor                         |
  |                                                               |
  |  +-------------------+     +---------------------------+      |
  |  | platform_adapter   |     | power_monitor             |      |
  |  | (CPU/mem/GPU/temp) |     | (sysfs power_supply)      |      |
  |  +---------+----------+     +-------------+-------------+      |
  |            |                              |                    |
  |            v                              v                    |
  |  +-----------------------------------------------------+      |
  |  |              aggregator_analyzer                     |      |
  |  |  (time-windowed cache + summary dict)                |      |
  |  +---------------------------+--------------------------+      |
  |                              |                                |
  |            +-----------------+------------------+             |
  |            |                                    |             |
  |            v                                    v             |
  |  +-------------------+              +-----------------------+ |
  |  |  web_dashboard /   |              |    ros2_bridge        | |
  |  |  prometheus / CLI  |              |  +-----------------+  | |
  |  +-------------------+              |  |  MonitorNode     |  | |
  |                                     |  +--------+--------+  | |
  |  +-------------------+              |           |           | |
  |  | inference_monitor  |------------>|           |           | |
  |  | (FPS/latency/GPU)  |              |           v           | |
  |  +-------------------+              |  /system/* topics     | |
  |                                     |  /inference/* topics  | |
  |                                     |  /monitor/status      | |
  |                                     +-----------------------+ |
  +---------------------------------------------------------------+
                              |
                   ROS2 DDS transport
                              |
            +-----------------+------------------+
            |                                    |
            v                                    v
      +-----------+                      +---------------+
      |  RViz /   |                      |  Foxglove     |
      |  rqt      |                      |  Studio       |
      +-----------+                      +---------------+
```

The bridge is an optional dependency.  When `rclpy` is not installed, the
monitor runs normally but silently skips ROS2 publishing (see Section 7).

---

## 2. Topics Reference

### 2.1 System Metrics

| Topic                    | Message Type        | Source Key          | Unit | Description                              |
|--------------------------|---------------------|---------------------|------|------------------------------------------|
| `/system/cpu_percent`    | `std_msgs/Float64`  | `cpu_avg`           | %    | Average CPU utilization over the window  |
| `/system/memory_mb`      | `std_msgs/Float64`  | `mem_used_avg_mb`   | MB   | Average physical memory usage            |
| `/system/power_watt`     | `std_msgs/Float64`  | `power_avg_watt`    | W    | Average power draw                       |
| `/system/temperature_c`  | `std_msgs/Float64`  | `temp_max_c`        | C    | Peak temperature over the window         |
| `/system/gpu_utilization`| `std_msgs/Float64`  | `gpu_percent`       | %    | GPU utilization (0 if no GPU detected)   |

All system topics are published on every cycle regardless of whether a GPU or
power sensor is present.  Missing fields default to `0.0`.

### 2.2 Inference Metrics

| Topic                   | Message Type        | Source Attribute      | Unit | Description                                  |
|-------------------------|---------------------|-----------------------|------|----------------------------------------------|
| `/inference/fps`        | `std_msgs/Float64`  | `fps`                 | fps  | Inference frames per second                  |
| `/inference/latency_p95`| `std_msgs/Float64`  | `latency_p95_ms`      | ms   | 95th-percentile inference latency            |
| `/inference/gpu_util`   | `std_msgs/Float64`  | `gpu_util_avg`        | %    | Average GPU utilization during inference     |

Inference topics are only published when an `InferenceMonitor` is active and
its results have been passed to `MonitorNode.publish_inference()`.

### 2.3 Aggregate Status

| Topic            | Message Type       | Format | Description                                      |
|------------------|--------------------|--------|--------------------------------------------------|
| `/monitor/status`| `std_msgs/String`  | JSON   | Full JSON blob of all metrics + diagnostics       |

The JSON payload is produced by `AggregatorAnalyzer.get_summary_dict()` and may
include fields such as `cpu_avg`, `mem_used_avg_mb`, `power_avg_watt`,
`temp_max_c`, `energy_joule`, `power_quality_worst`, and timeline arrays.

---

## 3. Quick Start

### 3.1 Prerequisites

| Requirement     | Minimum Version | Notes                                        |
|-----------------|-----------------|----------------------------------------------|
| ROS 2           | Humble (22.04)  | Iron, Jazzy, and Rolling also supported      |
| Python          | 3.8+            | Must match your ROS 2 Python installation    |
| colcon          | Latest          | Build tool for ROS 2 workspace packages      |

### 3.2 Installation

**Standalone (development / testing):**

```bash
pip install -e ".[ros2]"
```

**Inside a ROS 2 workspace:**

```bash
mkdir -p ~/ros2_ws/src && cd ~/ros2_ws/src
git clone https://github.com/your-org/ai-embedded-hw-monitoring.git ai_edge_monitor
cd ~/ros2_ws
pip install -r src/ai_edge_monitor/requirements.txt
colcon build --packages-select ai_edge_monitor
source install/setup.bash
```

### 3.3 Launch the Node

```bash
# Via launch file (recommended)
ros2 launch ai_edge_monitor monitor.launch.py

# Direct execution
ros2 run ai_edge_monitor monitor_node
```

### 3.4 Subscribe to Topics

```bash
# Echo all system metrics
ros2 topic echo /system/cpu_percent

# Echo the JSON status blob
ros2 topic echo /monitor/status

# List all published topics
ros2 topic list | grep -E "^/(system|inference|monitor)"
```

### 3.5 Programmatic Subscription (Python)

```python
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64, String
import json


class MetricsSubscriber(Node):
    def __init__(self):
        super().__init__("metrics_subscriber")
        self.create_subscription(Float64, "/system/cpu_percent", self._on_cpu, 10)
        self.create_subscription(String, "/monitor/status", self._on_status, 10)

    def _on_cpu(self, msg: Float64):
        self.get_logger().info(f"CPU: {msg.data:.1f}%")

    def _on_status(self, msg: String):
        data = json.loads(msg.data)
        self.get_logger().info(
            f"CPU={data.get('cpu_avg', 0):.1f}%  "
            f"MEM={data.get('mem_used_avg_mb', 0):.0f}MB  "
            f"PWR={data.get('power_avg_watt', 0):.1f}W"
        )


rclpy.init()
node = MetricsSubscriber()
rclpy.spin(node)
```

---

## 4. Launch Arguments

The `MonitorNode` constructor and the factory function accept the following
parameter:

| Parameter    | Type     | Default            | Description                              |
|-------------|----------|--------------------|------------------------------------------|
| `node_name`  | `string` | `"ai_edge_monitor"`| ROS2 node name registered with the graph |

When launched via `monitor.launch.py`, these additional ROS2 parameters are
available:

| Parameter          | Type     | Default  | Description                                         |
|-------------------|----------|----------|-----------------------------------------------------|
| `publish_rate`     | `double` | `1.0`    | Publishing frequency in Hz                          |
| `power_source`     | `string` | `"auto"` | Power probe: `auto`, `nvidia-smi`, `jetson`, `rpi`, `dummy` |
| `include_inference`| `bool`   | `true`   | Whether to publish `/inference/*` topics            |

**Example with overrides:**

```bash
ros2 launch ai_edge_monitor monitor.launch.py \
    publish_rate:=2.0 \
    node_name:=jetson_nano_monitor
```

**Example with topic remapping:**

```bash
ros2 run ai_edge_monitor monitor_node --ros-args \
    -r /system/cpu_percent:=/robot1/cpu \
    -r /system/memory_mb:=/robot1/memory \
    -r /monitor/status:=/robot1/status
```

---

## 5. Integration with Foxglove and RViz

### 5.1 Foxglove Studio

Foxglove Studio provides a web-based visualization tool that connects to ROS2
via the Foxglove WebSocket bridge.

**Setup:**

1. Start the Foxglove bridge in your ROS2 workspace:

   ```bash
   # Install if not already present
   sudo apt install ros-humble-foxglove-bridge
   ros2 launch foxglove_bridge foxglove_bridge_launch.xml
   ```

2. Open [Foxglove Studio](https://app.foxglove.dev) in a browser.

3. Connect to `ws://<device-ip>:8765`.

4. Add panels:
   - **Plot** panel: Add `/system/cpu_percent`, `/system/memory_mb`,
     `/system/power_watt`, `/system/temperature_c` to visualize time-series.
   - **Raw Messages** panel: Subscribe to `/monitor/status` to inspect the full
     JSON payload.
   - **Diagnostic** panel: Use the JSON status for custom diagnostic displays.

**Pre-built layout:**

Create a Foxglove layout file (`.json`) with these panels configured and share
it with the team.  The layout can be imported/exported via the Foxglove UI.

### 5.2 RViz2

RViz2 does not have built-in plotters for `Float64`, but you can use the
`rqt_plot` tool alongside it, or install the `rviz_2d_overlay_plugins` package
for custom display types.

**Using rqt_plot alongside RViz:**

```bash
# In a separate terminal
rqt_plot /system/cpu_percent /system/memory_mb /system/power_watt
```

**Using rviz_2d_overlay_plugins for heads-up display:**

```bash
sudo apt install ros-humble-rviz-2d-overlay-plugins
```

Then add an "Overlay Text" display in RViz2 subscribed to `/monitor/status` to
show a live text overlay of all metrics.

### 5.3 Data Recording with rosbag2

Record all monitoring topics for offline analysis:

```bash
ros2 bag record \
    /system/cpu_percent \
    /system/memory_mb \
    /system/power_watt \
    /system/temperature_c \
    /system/gpu_utilization \
    /inference/fps \
    /inference/latency_p95 \
    /inference/gpu_util \
    /monitor/status \
    --output monitoring_session
```

Replay later:

```bash
ros2 bag play monitoring_session
```

---

## 6. Multi-Device Setup for Fleet Monitoring

When monitoring multiple edge devices (e.g., a fleet of Jetson nodes), use ROS2
namespaces to isolate topics per device.

### 6.1 Namespace Configuration

```bash
# Device 1
ros2 run ai_edge_monitor monitor_node --ros-args \
    -r __ns:=/robot1 \
    -p node_name:=edge_monitor

# Device 2
ros2 run ai_edge_monitor monitor_node --ros-args \
    -r __ns:=/robot2 \
    -p node_name:=edge_monitor
```

This produces namespaced topics:

```
/robot1/edge_monitor/system/cpu_percent
/robot1/edge_monitor/system/memory_mb
...
/robot2/edge_monitor/system/cpu_percent
/robot2/edge_monitor/system/memory_mb
...
```

### 6.2 Launch File for Multi-Device

```python
# multi_device.launch.py
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    devices = ["jetson_a", "jetson_b", "rpi_c"]
    return LaunchDescription([
        Node(
            package="ai_edge_monitor",
            executable="monitor_node",
            namespace=device,
            name="edge_monitor",
            parameters=[{"publish_rate": 1.0}],
        )
        for device in devices
    ])
```

### 6.3 Centralized Monitoring with DDS

ROS2 DDS discovery works automatically across the network.  On the monitoring
station, subscribe to all namespaces:

```bash
ros2 topic list | grep system/cpu_percent
# /jetson_a/edge_monitor/system/cpu_percent
# /jetson_b/edge_monitor/system/cpu_percent
# /rpi_c/edge_monitor/system/cpu_percent
```

For cross-subnet discovery, configure DDS (e.g., CycloneDDS) with explicit
peer addresses in `CYCLONEDDS_URI`.

---

## 7. Troubleshooting

### 7.1 `ModuleNotFoundError: No module named 'rclpy'`

ROS2 Python packages are not on the current Python path.

```bash
source /opt/ros/humble/setup.bash
```

If running in a virtual environment, ensure the venv was created with
`--system-site-packages` or install `rclpy` into it:

```bash
pip install rclpy
```

### 7.2 Node Starts but No Topics Appear

```bash
# Verify the node is running
ros2 node list
ros2 node info /ai_edge_monitor

# Check that publish_rate > 0
ros2 param get /ai_edge_monitor publish_rate
```

If the node info shows no publishers, the node may have started without `rclpy`.
Check the log for the warning: `"ROS2 (rclpy) not available, MonitorNode disabled"`.

### 7.3 `No executable found` When Running `ros2 run`

The package was not built or the install space was not sourced:

```bash
colcon build --packages-select ai_edge_monitor
source install/setup.bash
```

### 7.4 Topics Publish but Subscriber Receives Nothing

Check QoS compatibility.  The monitor uses the default QoS profile
(`RELIABLE`, `VOLATILE`, depth 10).  If your subscriber uses a different
profile (e.g., `BEST_EFFORT`), the connection will not be established.

```bash
ros2 topic info -v /system/cpu_percent
```

### 7.5 Graceful Degradation Without rclpy

When `rclpy` is not installed, the entire monitoring pipeline continues to
operate normally.  Only the ROS2 bridge is disabled:

- CLI (`ai-edge-monitor run`) -- unaffected
- Web dashboard -- unaffected
- Prometheus exporter -- unaffected
- File exporters (JSONL, CSV, PNG) -- unaffected

The `create_monitor_node()` factory returns `None` and logs a warning.  All
`publish_*` methods are no-ops when `HAS_ROS2` is `False`.  This is by design:
the bridge is a non-critical sidecar, not a required dependency.

### 7.6 High CPU Usage from the Node

Reduce the publish rate:

```bash
ros2 param set /ai_edge_monitor publish_rate 0.5
```

The default 1 Hz rate is suitable for most dashboards.  Rates above 10 Hz are
generally unnecessary for monitoring data.

---

## 8. API Reference

### 8.1 `MonitorNode`

```python
class MonitorNode(rclpy.node.Node):
    """ROS2 node publishing system + inference monitoring data."""

    def __init__(self, node_name: str = "ai_edge_monitor") -> None:
        """Initialize publishers for all topics.

        Creates 5 system topic publishers (/system/*),
        3 inference topic publishers (/inference/*),
        and 1 status publisher (/monitor/status).

        All publishers use std_msgs/Float64 (or String for status)
        with a queue depth of 10.
        """

    def publish_metrics(self, summary: Dict[str, Any]) -> None:
        """Publish system metrics from AggregatorAnalyzer.get_summary_dict().

        Reads the following keys from summary:
          - cpu_avg       -> /system/cpu_percent
          - mem_used_avg_mb -> /system/memory_mb
          - power_avg_watt  -> /system/power_watt
          - temp_max_c      -> /system/temperature_c
          - gpu_percent     -> /system/gpu_utilization

        Missing keys are silently skipped (no message published for that topic).
        """

    def publish_inference(self, inference_results: Any) -> None:
        """Publish inference metrics from InferenceMonitor.results.

        Reads the following attributes from inference_results:
          - fps             -> /inference/fps
          - latency_p95_ms  -> /inference/latency_p95
          - gpu_util_avg    -> /inference/gpu_util

        The object is duck-typed; any object with these optional attributes
        will work.  Missing attributes are silently skipped.
        """

    def publish_status(self, status_dict: Dict[str, Any]) -> None:
        """Publish JSON status string to /monitor/status.

        Serializes status_dict to JSON using json.dumps() with
        ensure_ascii=False and default=str for non-serializable values.
        """
```

### 8.2 `create_monitor_node` Factory

```python
def create_monitor_node(
    node_name: str = "ai_edge_monitor",
) -> Optional[MonitorNode]:
    """Create a MonitorNode or return None if ROS2 is unavailable.

    This is the recommended way to instantiate the node in application code.
    It handles the case where rclpy is not installed by returning None and
    logging a warning, rather than raising an ImportError.

    Args:
        node_name: ROS2 node name.  Defaults to "ai_edge_monitor".

    Returns:
        A MonitorNode instance if rclpy is available, None otherwise.
    """
```

**Usage:**

```python
from ros2_bridge import create_monitor_node

node = create_monitor_node("my_jetson_monitor")
if node is not None:
    node.publish_metrics(analyzer.get_summary_dict())
    node.publish_inference(inference_results)
    node.publish_status(full_status_dict)
```

### 8.3 `HAS_ROS2` Flag

```python
from ros2_bridge import HAS_ROS2

if HAS_ROS2:
    # rclpy is available; ROS2 features are enabled
    ...
else:
    # rclpy not installed; running in standalone mode
    ...
```

### 8.4 Module Constants

The bridge defines the following topic-to-key mappings (internal, but useful
for understanding the data flow):

| Constant            | Purpose                                  |
|---------------------|------------------------------------------|
| `_SYSTEM_TOPICS`    | Maps system metric keys to topic names   |
| `_INFERENCE_TOPICS` | Maps inference metric keys to topic names|
| `_SUMMARY_KEY_MAP`  | Maps publisher keys to summary dict keys |

---

## 9. Complete Integration Example

A full working example combining monitoring, inference, and ROS2 publishing:

```python
import time
from collector import Collector, CollectorConfig
from aggregator_analyzer import AggregatorAnalyzer
from inference_monitor import InferenceMonitor
from ros2_bridge import create_monitor_node

# Initialize components
analyzer = AggregatorAnalyzer(window_sec=60)
collector = Collector(CollectorConfig(interval_ms=1000), analyzer=analyzer)
node = create_monitor_node("jetson_nano_monitor")

if node is None:
    raise RuntimeError("ROS2 not available. Source /opt/ros/humble/setup.bash")

# Start data collection
collector.start()

try:
    while rclpy.ok():
        summary = analyzer.get_summary_dict()
        node.publish_metrics(summary)
        node.publish_status(summary)
        time.sleep(1.0)  # 1 Hz publish rate
except KeyboardInterrupt:
    pass
finally:
    collector.stop()
```

To also publish inference metrics:

```python
with InferenceMonitor("model.onnx") as monitor:
    for frame in video_stream:
        result = model.infer(frame)
        monitor.record_inference()

# After inference completes
node.publish_inference(monitor.results)
```
