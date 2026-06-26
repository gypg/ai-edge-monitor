#pragma once
/// @file system_info.hpp
/// @brief Lightweight Linux /proc and /sys readers for embedded device monitoring.
///
/// Designed as the C++ native collector behind ai-edge-monitor's Python
/// ``ProcfsProbe``.  All functions are synchronous, allocate minimally, and
/// finish in < 1 ms on typical ARM/x86 edge hardware.
///
/// Platform: Linux only (Jetson, Raspberry Pi, x86 edge servers).

#include <cstdint>
#include <string>
#include <vector>

namespace ai_edge {

/// Per-CPU snapshot.
struct CpuInfo {
    float percent{0.0f};        ///< Aggregate CPU utilisation 0-100 (delta between two calls).
    float frequency_mhz{0.0f}; ///< Current frequency from /proc/cpuinfo (0 if unavailable).
    int   cores{0};             ///< Number of logical cores.
    std::string model_name;     ///< Model name from /proc/cpuinfo.
};

/// Physical / swap memory snapshot.
struct MemoryInfo {
    uint64_t total_kb{0};      ///< MemTotal.
    uint64_t used_kb{0};       ///< MemTotal - MemAvailable.
    uint64_t available_kb{0};  ///< MemAvailable.
    float    percent{0.0f};    ///< used / total * 100.
};

/// Top-level system snapshot combining CPU, memory, temperature and identity.
struct SystemInfo {
    CpuInfo     cpu;
    MemoryInfo  memory;
    float       temperature_c{-1.0f}; ///< SoC / CPU temperature in Celsius, -1 if unavailable.
    std::string hostname;             ///< From gethostname() or /proc/sys/kernel/hostname.
    std::string platform;             ///< "linux", "jetson", or "rpi" (detected heuristically).
};

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Collect a full system snapshot (CPU, memory, temperature, identity).
/// This is the primary entry point -- equivalent to ``ProcfsProbe.read_metrics()``.
SystemInfo collect_system_info();

/// Return per-core CPU percentages (delta between two /proc/stat reads).
/// Returns an empty vector on error.
std::vector<float> collect_per_core_cpu();

/// Read memory info from /proc/meminfo.
MemoryInfo collect_memory_info();

/// Read CPU info from /proc/stat (delta) and /proc/cpuinfo.
CpuInfo collect_cpu_info();

/// Read temperature from the first available thermal zone.
/// Returns -1.0f when no sensor is found or reading fails.
float collect_temperature();

} // namespace ai_edge
