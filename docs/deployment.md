# Deployment Guide

> Complete deployment reference for `ai-edge-monitor` on Jetson, Raspberry Pi, x86 edge devices, Docker, and ROS2 environments.

---

## 1. Prerequisites

| Requirement | Jetson | Raspberry Pi | x86 Edge |
|------------|--------|-------------|----------|
| OS | JetPack 4.6+ / L4T | Raspberry Pi OS (Bullseye+) | Ubuntu 20.04+ / Debian 11+ |
| Python | 3.8+ | 3.8+ | 3.8+ |
| RAM | 2 GB+ | 1 GB+ | 2 GB+ |
| Disk | 500 MB free | 500 MB free | 500 MB free |
| CMake (C++ layer) | 3.14+ | 3.14+ | 3.14+ |
| NVIDIA driver (GPU) | Included in JetPack | N/A | 525+ (nvidia-smi) |

---

## 2. NVIDIA Jetson Deployment

### 2.1 Jetson Nano / Xavier / Orin

**Install system dependencies:**

```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv git cmake build-essential
```

**Install the project:**

```bash
git clone <repo-url> ai-edge-monitor
cd ai-edge-monitor

# Core install (zero dependencies)
pip3 install -e .

# Full install (psutil + matplotlib)
pip3 install -e ".[all]"
```

**Verify GPU detection:**

```bash
# JetPack includes nvidia-smi for Tegra
nvidia-smi

# Quick test with ai-edge-monitor
ai-edge-monitor run --duration 10
```

Expected output: `CompositeProbe` combining psutil + nvidia-smi, showing CPU, memory, GPU utilization, and VRAM.

### 2.2 Jetson Power Monitoring

Jetson devices expose power rails through sysfs:

```bash
# Check available power sensors
ls /sys/class/power_supply/

# Common paths on Jetson
/sys/class/power_supply/BAT/          # Battery (if present)
/sys/class/power_supply/ac/           # AC adapter
```

The `power_monitor` module automatically detects and reads these sensors.

### 2.3 Building the C++ Native Layer on Jetson

```bash
cd cpp_src
cmake -B build -DENABLE_NEON=ON -DBUILD_TESTS=ON
cmake --build build -j$(nproc)

# Run C++ unit tests
./build/tests/ai_edge_native_tests

# Build with pybind11 for Python integration
cmake -B build-py -DENABLE_NEON=ON -DBUILD_PYTHON=ON \
      -Dpybind11_DIR=$(python3 -m pybind11 --cmakedir)
cmake --build build-py -j$(nproc)
```

The NEON SIMD flag enables 3x+ acceleration for P95 percentile computation. On Jetson Nano (ARM Cortex-A57), this reduces per-sample computation overhead from ~0.15ms to ~0.04ms.

### 2.4 Jetson-Specific Tuning

```yaml
# monitor.yaml for Jetson Nano
duration_sec: 300
interval_ms: 2000          # Lower frequency to reduce overhead on limited CPU
output_dir: /tmp/reports
device: auto
exporters:
  - jsonl
  - csv
  - summary
thresholds:
  cpu_high: 90             # Jetson throttles at high CPU
  temp_high: 85            # Tegra thermal limit
  power_high_mw: 10000     # 10W power budget for Nano
```

Set Jetson power mode for consistent benchmarking:

```bash
# Jetson Nano: 10W mode (2 cores)
sudo nvpmodel -m 1
sudo jetson_clocks

# Jetson Xavier: MAXN mode
sudo nvpmodel -m 0
sudo jetson_clocks
```

---

## 3. Raspberry Pi Deployment

### 3.1 Raspberry Pi 4 / 5

**Install system dependencies:**

```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv git cmake build-essential
```

**Install the project:**

```bash
git clone <repo-url> ai-edge-monitor
cd ai-edge-monitor
pip3 install -e ".[all]"
```

**Quick verification:**

```bash
ai-edge-monitor run --duration 10
```

On RPi, the probe chain is: `procfs -> psutil -> dummy`. No GPU monitoring via nvidia-smi (RPi uses VideoCore). Temperature reads from `/sys/class/thermal/`.

### 3.2 Raspberry Pi Temperature Monitoring

```bash
# Verify thermal zone access
cat /sys/class/thermal/thermal_zone0/temp
# Output: 45678  (45.7 C)

# vcgencmd for GPU memory
vcgencmd get_mem gpu
```

### 3.3 Cross-Compiling C++ for Raspberry Pi

From a Linux x86 host with cross-compilation tools installed:

```bash
sudo apt-get install gcc-aarch64-linux-gnu g++-aarch64-linux-gnu

cd cpp_src
cmake -B build-rpi \
      -DCMAKE_TOOLCHAIN_FILE=toolchain-aarch64.cmake \
      -DENABLE_NEON=ON \
      -DBUILD_TESTS=OFF
cmake --build build-rpi -j$(nproc)
```

Transfer the built library to the Raspberry Pi:

```bash
scp build-rpi/libai_edge_native.a pi@<rpi-ip>:/opt/ai-edge-monitor/
```

For 32-bit Raspberry Pi OS (armhf), use `toolchain-armhf.cmake` instead:

```bash
cmake -B build-armhf \
      -DCMAKE_TOOLCHAIN_FILE=toolchain-armhf.cmake \
      -DENABLE_NEON=ON
cmake --build build-armhf -j$(nproc)
```

### 3.4 Raspberry Pi-Specific Tuning

```yaml
# monitor.yaml for Raspberry Pi 4
duration_sec: 300
interval_ms: 2000          # Reduce sampling rate on limited CPU
output_dir: /tmp/reports
device: auto
exporters:
  - jsonl
  - summary
  - png
thresholds:
  cpu_high: 85
  temp_high: 75            # RPi thermal throttle at 80C
```

Disable WiFi power saving for consistent network I/O monitoring:

```bash
sudo iw wlan0 set power_save off
```

---

## 4. x86 Edge Device Deployment

### 4.1 Standard Linux Installation

```bash
git clone <repo-url> ai-edge-monitor
cd ai-edge-monitor

# Full install
pip install -e ".[all]"

# With inference framework support
pip install -e ".[all-ml]"
```

### 4.2 Building C++ with AVX2

```bash
cd cpp_src
cmake -B build -DENABLE_AVX2=ON -DBUILD_TESTS=ON -DBUILD_PYTHON=ON
cmake --build build -j$(nproc)
```

### 4.3 NVIDIA GPU on x86

For x86 devices with discrete NVIDIA GPUs:

```bash
# Verify nvidia-smi access
nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu --format=csv

# Run with GPU monitoring
ai-edge-monitor run --duration 60
```

The `CompositeProbe` automatically detects and combines CPU + GPU metrics.

### 4.4 x86 Power Monitoring

```bash
# Intel RAPL (Running Average Power Limit)
ls /sys/class/power_supply/
cat /sys/class/power_supply/BAT/power_now  # milliwatts
```

---

## 5. Docker Deployment

### 5.1 Build the Image

```bash
docker build -t ai-edge-monitor:latest .
```

### 5.2 Run with Docker Compose

Create `monitor.yaml`:

```yaml
duration_sec: 30
interval_ms: 1000
output_dir: reports/docker
force_dummy: true
exporters:
  - jsonl
  - csv
  - summary
  - png
thresholds:
  cpu_high: 85
  temp_high: 80
```

Run:

```bash
mkdir -p reports
docker compose up --build ai-edge-monitor
```

### 5.3 GPU Access in Docker (Jetson / x86)

For NVIDIA GPU access inside Docker containers:

```bash
# Jetson with JetPack
docker run --rm -it \
    --runtime nvidia \
    -v $(pwd)/reports:/app/reports \
    ai-edge-monitor:latest \
    ai-edge-monitor run --duration 30 --out /app/reports

# x86 with NVIDIA Container Toolkit
docker run --rm -it \
    --gpus all \
    -v $(pwd)/reports:/app/reports \
    ai-edge-monitor:latest \
    ai-edge-monitor run --duration 30 --out /app/reports
```

### 5.4 Multi-Architecture Docker Build

```bash
# Build for both x86 and ARM
docker buildx build --platform linux/amd64,linux/arm64 \
    -t ai-edge-monitor:multiarch --push .
```

---

## 6. ROS2 Integration

### 6.1 Install with ROS2 Support

```bash
# Ensure ROS2 Humble (or later) is sourced
source /opt/ros/humble/setup.bash

# Install with ROS2 extras
pip install -e ".[ros2]"
```

### 6.2 Run as a ROS2 Node

```bash
# Using the provided launch file
ros2 launch launch/monitor.launch.py

# Or manually with parameters
ros2 run ai_edge_monitor monitor_node --ros-args \
    -p duration_sec:=60 \
    -p interval_ms:=1000
```

### 6.3 Published Topics

| Topic | Type | Description |
|-------|------|-------------|
| `/cpu` | `std_msgs/Float32` | CPU utilization (%) |
| `/memory` | `std_msgs/Float32` | Memory utilization (%) |
| `/power` | `std_msgs/Float32` | Power consumption (W) |
| `/temperature` | `std_msgs/Float32` | Temperature (C) |
| `/inference/fps` | `std_msgs/Float32` | Inference FPS |
| `/inference/latency` | `std_msgs/Float32` | Inference latency (ms) |
| `/inference/gpu_util` | `std_msgs/Float32` | GPU utilization during inference (%) |

### 6.4 Subscribing to Monitor Data

```python
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32

class MonitorSubscriber(Node):
    def __init__(self):
        super().__init__('monitor_subscriber')
        self.create_subscription(Float32, '/temperature', self.temp_callback, 10)

    def temp_callback(self, msg: Float32):
        self.get_logger().info(f'Temperature: {msg.data:.1f} C')
        if msg.data > 80.0:
            self.get_logger().warn('Thermal throttle risk!')
```

### 6.5 Launch File Configuration

Edit `launch/monitor.launch.py` to customize:

```python
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='ai_edge_monitor',
            executable='monitor_node',
            parameters=[{
                'duration_sec': 300,
                'interval_ms': 1000,
                'force_dummy': False,
            }],
            output='screen',
        )
    ])
```

---

## 7. Web Dashboard Deployment

The web dashboard provides a real-time monitoring UI accessible from any browser.

### 7.1 Start the Dashboard

```bash
# CLI subcommand
ai-edge-monitor dashboard --port 17429 --duration 300

# Standalone script
python dashboard.py --port 17429 --force-dummy  # Test mode

# Access: http://<device-ip>:17429
```

### 7.2 Dashboard Features

- **Real-time charts**: CPU / memory / power timeline (Chart.js, 3-second polling)
- **System overview**: gauges for CPU, memory, power, temperature, disk usage
- **Alert panel**: active alerts and history (color-graded: INFO, WARNING, ERROR, CRITICAL)
- **Guardian health**: monitoring process CPU/RSS overhead, degrade state, circuit breaker
- **Network I/O**: send/receive rates, connection counts

### 7.3 Reverse Proxy (nginx)

For production deployments with TLS termination:

```nginx
server {
    listen 443 ssl;
    server_name monitor.example.com;

    ssl_certificate /etc/ssl/certs/monitor.pem;
    ssl_certificate_key /etc/ssl/private/monitor.key;

    location / {
        proxy_pass http://127.0.0.1:17429;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## 8. Prometheus Integration

### 8.1 Enable the Exporter

```python
from prometheus_exporter import PrometheusExporter

exporter = PrometheusExporter(port=9090)
exporter.start_http_server()
exporter.update(window_summary)  # Call with each new WindowSummary
```

### 8.2 Prometheus Scrape Configuration

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'ai-edge-monitor'
    static_configs:
      - targets: ['<device-ip>:9090']
    scrape_interval: 15s
```

---

## 9. Performance Tuning

### 9.1 Overhead Guarantees

The monitoring pipeline is designed as a sidecar with minimal resource footprint:

| Metric | Target | Measurement Method |
|--------|--------|--------------------|
| CPU overhead (idle) | < 0.05 ms / sample | 30s x 100ms baseline test |
| RSS growth | < 0.05 MB / 30s | Baseline tests on each module |
| Latency added to inference | < 1% of frame time | Non-blocking sampler design |

### 9.2 Sampling Frequency Guidelines

| Device | Recommended Interval | Rationale |
|--------|---------------------|-----------|
| Jetson Nano | 2000 ms | Limited 4-core CPU |
| Jetson Xavier/Orin | 1000 ms | 6-8 core, more headroom |
| Raspberry Pi 4 | 2000 ms | Thermal sensitivity |
| x86 edge server | 500-1000 ms | Ample CPU headroom |

### 9.3 Reducing Overhead on Constrained Devices

```yaml
# Minimal configuration for resource-constrained devices
duration_sec: 300
interval_ms: 5000          # 5-second sampling
output_dir: /tmp/reports
exporters:
  - jsonl                  # Only JSONL, skip visualization
thresholds:
  cpu_high: 90
  temp_high: 80
```

Disable the web dashboard and Prometheus exporter on constrained devices. Use CLI-only mode and export JSONL for offline analysis.

### 9.4 Memory Profiling

Use the built-in performance profiler to measure monitoring overhead:

```python
from performance_profiler import OperationProfiler

profiler = OperationProfiler("collection_cycle")
with profiler.measure():
    result = collector.collect_once()

sample = profiler.last_sample
print(f"Duration: {sample.duration_ms:.2f} ms, RSS delta: {sample.rss_delta_mb:.3f} MB")
```

---

## 10. Verification and Smoke Tests

### 10.1 Post-Deployment Checklist

```bash
# 1. Verify probe detection
python -c "from platform_adapter import select_default_probe; p = select_default_probe(); print(type(p).__name__)"

# 2. Run 10-second smoke test
ai-edge-monitor run --duration 10 --out /tmp/smoke

# 3. Verify output files
ls -la /tmp/smoke/
# Expected: metrics.jsonl, metrics.csv, summary.json, report.png, report.png.json

# 4. Run integration test
python integration/test_e2e_collect_to_report.py --duration-sec 30

# 5. (Optional) Run full system test
python integration/test_full_system.py
```

### 10.2 Device Acceptance Criteria

The full device acceptance procedure is documented in `docs/test_report/real_hardware_validation.md`. The 7-pass criteria are:

1. All baseline tests pass with RSS < 1 MB growth
2. All integration tests pass
3. E2E test produces valid PNG report
4. Guardian degrade/recover cycle works
5. No crashes during 60-second continuous monitoring
6. CPU overhead stays below 5ms per sample
7. All exported formats (JSONL, CSV, JSON) validate

---

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `DummyProbe` selected on Jetson | nvidia-smi not in PATH | `export PATH=$PATH:/usr/local/cuda/bin` |
| Temperature reads 0 | Thermal zone permissions | `sudo chmod a+r /sys/class/thermal/thermal_zone*/temp` |
| Power reads fail | No power_supply in sysfs | Expected on RPi; use external hardware |
| ROS2 node crashes | rclpy not installed | `pip install -e ".[ros2]"` |
| PNG report empty | Matplotlib backend issue | Falls back to stdlib renderer automatically |
| High memory growth | Large window size | Reduce `power_window_size` in config |
