# System Architecture

> Detailed architectural reference for `ai-edge-monitor`.
> For the module overview and quick start, see [README.md](../README.md).

---

## 1. High-Level Architecture

```
 +-------------------------------------------------------------------+
 |                        ai-edge-monitor                            |
 |                                                                   |
 |  +-----------+  +--------------+  +----------------+              |
 |  | collector |  | platform     |  | memory_        |              |
 |  |           |  | _adapter     |  | diagnostics    |              |
 |  +-----+-----+  +------+-------+  +-------+--------+              |
 |        |               |                  |                       |
 |        v               v                  v                       |
 |  +-----------+  +--------------+  +----------------+              |
 |  | aggregator|  | inference    |  | ai_advisor     |              |
 |  | _analyzer |  | _monitor     |  | (rules + ML)   |              |
 |  +-----+-----+  +------+-------+  +-------+--------+              |
 |        |               |                  |                       |
 |        v               v                  v                       |
 |  +-----------+  +--------------+  +----------------+              |
 |  | ros2      |  | native       |  | performance    |              |
 |  | _bridge   |  | _collector   |  | _profiler      |              |
 |  +-----------+  | (C++/pybind) |  +----------------+              |
 |                  +--------------+                                  |
 +-------------------------------------------------------------------+

 Cross-cutting concerns:
   config_manager  -- YAML/CLI configuration
   runtime_guardian -- self-watchdog, degrade/recover
   prometheus_exporter -- /metrics endpoint
   storage_exporter  -- JSONL / CSV / summary.json
   visualizer        -- matplotlib + stdlib PNG fallback
   web_dashboard     -- real-time monitoring UI
   alert_manager     -- threshold-based alerting
   data_quality      -- data validation and quality checks
   scenarios         -- synthetic workload generators
```

---

## 2. Data Flow

The monitoring pipeline follows a strict directional flow to prevent circular dependencies:

```
 +----------+     +-------------+     +-----------+     +-----------+
 | Hardware |---->| Collectors  |---->| Analyzer  |---->| Consumers |
 | Sources  |     | (samplers)  |     | (aggreg.) |     | (exports) |
 +----------+     +-------------+     +-----------+     +-----------+

 Detailed:

 +-------------------+     RawMetrics       +--------------------+
 | platform_adapter  |--------------------->|                    |
 | (CPU/mem/temp/GPU)|                      |                    |
 +-------------------+                      | aggregator_analyzer|
                                            | (time-windowed     |
 +-------------------+   PowerStatsFrame    |  ring buffers)     |
 | power_monitor     |--------------------->|                    |
 | (watts/energy)    |                      +--------+-----------+
 +-------------------+                              |
                                                    v
                             +------+  +------+  +------+  +------+
                             | JSONL|  | CSV  |  |Prom. |  | ROS2 |
                             +------+  +------+  +------+  +------+
                                                    |
                                              +-----+-----+
                                              | Visualizer |
                                              | (PNG/SVG)  |
                                              +------------+
```

### 2.1 Collection Layer

The collection layer is responsible for acquiring raw hardware metrics from the operating system and hardware interfaces.

**platform_adapter** probes (priority order):

```
embedded (Jetson/Raspberry Pi)  -->  procfs (/proc/stat, /proc/meminfo)  -->  psutil  -->  dummy
```

Optional GPU / accelerator probes are automatically composed when available:
- `NvidiaSmiProbe` reads discrete NVIDIA GPUs via `nvidia-smi`
- `JetsonProbe` reads Jetson integrated GPU and power via `jtop` / `tegrastats`

**power_monitor** sources (priority order):

```
sysfs (/sys/class/power_supply)  -->  jetson (jtop/tegrastats)  -->  dummy
```

Each sampler runs on a `time.monotonic()` + sleep drift-compensated timer, avoiding busy-wait loops.

### 2.2 Aggregation Layer

`AggregatorAnalyzer` maintains two independent ring buffers (one per source type) and produces `WindowSummary` dataclasses containing:

- CPU mean / P95 / max
- Memory mean / max / trend
- Temperature mean / max
- Power mean / P95 / max
- Energy (joules over window)
- Data quality score (0-100)

Power values are consumed from `PowerStatsFrame` directly (not re-aggregated from raw samples) to avoid duplication of normalization logic and quality propagation.

### 2.3 Advisory Layer

`ai_advisor.DiagnosticEngine` runs 10+ rules against `WindowSummary`:

| Rule Category | Detection Method |
|---------------|-----------------|
| Thermal | Temperature threshold + trend |
| CPU bottleneck | Sustained high utilization + inference context |
| Memory leak | RSS linear regression over sliding window |
| GPU saturation | VRAM + utilization correlation |
| Power budget | Energy exceedance over time |
| FPS degradation | Latency P95 vs target |

Each diagnosis produces a structured `{category, priority, suggestion, evidence}` object. The `DeploymentAssessment` scorer synthesizes all diagnoses into a 0-100 readiness score.

### 2.4 Export Layer

Multiple exporters operate in parallel from the same `WindowSummary`:

- `JsonlExporter` -- line-delimited JSON for log pipelines
- `CsvExporter` -- tabular format for pandas / Excel
- `SummaryExporter` -- aggregated JSON for automation
- `PrometheusExporter` -- text exposition format at `/metrics`
- `MonitorNode` (ROS2) -- topic publication to `/cpu`, `/memory`, `/power`, `/temperature`, `/inference/*`

---

## 3. C++/Python Hybrid Architecture

The project uses a hybrid architecture where performance-critical paths have C++ implementations with Python fallbacks.

### 3.1 Native Collector Module

```
 cpp_src/
 +-- system_info.cpp      # /proc/stat parsing, CPU topology
 +-- memory_monitor.cpp   # /proc/meminfo, RSS tracking
 +-- optimized_kernels.cpp # NEON/AVX2 SIMD-accelerated P95 computation
 +-- include/
 |   +-- system_info.hpp
 |   +-- memory_monitor.hpp
 |   +-- optimized_kernels.hpp
 |   +-- gpu_tracker.h
 |   +-- leak_detector.h
 +-- pybind/
 |   +-- bindings.cpp     # pybind11: exports NativeProbe, NeonStats
 +-- tests/               # Google Test C++ unit tests
```

### 3.2 Python Fallback Chain

```
 try: from _native_collector import NativeProbe
 except ImportError:
     # Fall back to ProcfsProbe (Linux) or PsutilProbe (cross-platform)
     # Fall back to DummyProbe if nothing available
```

The `select_probe()` function in `native_collector/__init__.py` implements the full chain:

```
NativeProbe  -->  ProcfsProbe  -->  PsutilProbe  -->  DummyProbe
```

### 3.3 SIMD Acceleration

The `optimized_kernels.cpp` implements P95 computation using:

- **ARM NEON** (`-mfpu=neon`, `AI_EDGE_HAS_NEON=1`): 3x+ speedup over scalar C++
- **x86 AVX2** (`-mavx2 -mfma`, `AI_EDGE_HAS_AVX2=1`): 4x+ speedup over scalar C++

Both are compile-time flags controlled by CMake options `ENABLE_NEON` and `ENABLE_AVX2`.

---

## 4. Module Dependency Graph

```
 cli
  +-- app_orchestrator
  |    +-- config_manager
  |    +-- collector
  |    |    +-- platform_adapter
  |    |    |    +-- native_collector (optional)
  |    |    +-- power_monitor
  |    |    +-- aggregator_analyzer
  |    +-- scheduler
  |    +-- storage_exporter
  |    +-- visualizer
  |    +-- prometheus_exporter
  |    +-- runtime_guardian
  +-- scenarios (standalone)

 web_dashboard
  +-- app_orchestrator
  +-- ai_advisor

 ros2_bridge
  +-- collector (metrics pipeline)
  +-- inference_monitor (optional)

 inference_monitor
  +-- platform_adapter (GPU context)
  +-- TensorRT / ONNX Runtime (optional, runtime-detected)

 memory_diagnostics
  +-- procfs (/proc/<pid>/*)
  +-- GPU VRAM tracking (optional)

 performance_profiler
  +-- cgroup v1/v2 (optional)
  +-- /proc/self/stat
```

### 4.1 Dependency Rules

1. **No circular dependencies.** Modules communicate through data objects (`RawMetrics`, `PowerStatsFrame`, `WindowSummary`), not direct cross-calls.
2. **Optional dependencies degrade gracefully.** Every optional import (psutil, matplotlib, rclpy, tensorrt, onnxruntime) is wrapped in try/except with a `HAS_*` flag and fallback behavior.
3. **Zero mandatory runtime dependencies.** The core monitoring loop runs with Python 3.8+ stdlib only. All third-party packages are optional enhancements.

---

## 5. Key Design Decisions

### 5.1 Immutable Data Objects

All data transfer objects (`RawMetrics`, `PowerStatsFrame`, `WindowSummary`, `ProfileSample`) are `@dataclass` with no mutable post-construction state. Consumers receive snapshots, not live references.

### 5.2 Non-Busy-Wait Scheduling

All periodic operations use `time.monotonic()` + drift-compensated `time.sleep()`. No spin loops, no `time.time()` (which is affected by NTP adjustments).

### 5.3 Graceful Degradation

The `runtime_guardian` self-monitor uses hysteresis (separate high/low thresholds) to prevent oscillation between degraded and healthy states. Each subsystem that fails triggers a controlled degradation callback rather than crashing the pipeline.

### 5.4 Zero-Dependency Visualization

The `visualizer` module falls back to a stdlib-only PNG renderer (using `zlib` and hand-written PNG chunks) when matplotlib is unavailable. This ensures CI pipelines can generate verification reports without installing graphical libraries.

### 5.5 Dual Aggregation Paths

Platform metrics (`RawMetrics`) and power metrics (`PowerStatsFrame`) flow through independent ring buffers in the aggregator. This design ensures that a stall on one data source (e.g., power monitor temporarily unavailable) cannot block ingestion from the other source.

### 5.6 Sidecar Reports

Every PNG report is accompanied by a `.png.json` sidecar file containing the full `WindowSummary` data. This allows downstream automation to consume report metadata without parsing images.

---

## 6. Thread Model

```
 Main Thread
   |-- Orchestrator.run()
   |     |-- PlatformSampler timer thread (1 Hz default)
   |     |-- PowerSampler timer thread (1 Hz default)
   |     |-- RuntimeGuardian watchdog thread (0.2 Hz)
   |     |-- AggregatorAnalyzer (lock-protected ring buffers)
   |     '-- Exporter pipeline (write-on-snapshot)
   |
   |-- [optional] MonitorNode (ROS2 spinner thread)
   '-- [optional] PrometheusExporter (HTTP server thread)
```

All shared state is protected by `threading.Lock`. Samplers write to their respective ring buffers atomically. The aggregator reads both buffers under lock to produce a consistent snapshot.

---

## 7. Configuration Flow

```
 Default values (code)
        |
        v
 YAML file (--config)       overrides defaults
        |
        v
 CLI arguments (--duration, --out, ...)       overrides YAML
        |
        v
 MonitorConfig (immutable after construction)
        |
        v
 Orchestrator assembly
```

The `config_manager` module implements a three-layer merge: code defaults, YAML file, CLI overrides. The resulting `MonitorConfig` is immutable once constructed.
