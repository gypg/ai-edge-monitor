/// @file system_info.cpp
/// @brief Linux /proc and /sys readers for embedded hardware monitoring.
///
/// Mirrors the Python ``ProcfsProbe`` (src/platform_adapter/procfs_probe.py)
/// using only POSIX APIs and the C++17 standard library.  Every public
/// function is thread-safe w.r.t. its own state but relies on the caller to
/// serialize ``collect_cpu_info`` / ``collect_per_core_cpu`` if CPU-delta
/// semantics are desired (the module-level static keeps the previous snapshot).

#include "include/system_info.hpp"

#include <algorithm>
#include <array>
#include <cstdio>      // gethostname
#include <cstring>
#include <dirent.h>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unistd.h>    // gethostname
#include <vector>

namespace ai_edge {

// ===========================================================================
// Internal helpers
// ===========================================================================

namespace {

/// Read the entire contents of a small procfs/sysfs file into @p out.
/// Returns true on success.  Silently returns false on any I/O error so that
/// callers can degrade gracefully.
bool read_file(const char* path, std::string& out) {
    std::ifstream fh(path, std::ios::in);
    if (!fh.is_open()) {
        return false;
    }
    std::ostringstream ss;
    ss << fh.rdbuf();
    out = ss.str();
    return true;
}

/// Tokenise the first line of /proc/stat into its numeric columns.
/// The first token (the "cpu" / "cpuN" label) is skipped.
struct StatLine {
    int64_t idle;   // idle + iowait
    int64_t total;  // sum of all jiffy columns
};

bool parse_stat_line(const std::string& line, StatLine& out) {
    std::istringstream ss(line);
    std::string label;
    if (!(ss >> label)) {
        return false;
    }
    // Expect "cpu" or "cpu0", "cpu1", ...
    if (label.compare(0, 3, "cpu") != 0) {
        return false;
    }

    // Read all numeric fields: user nice system idle iowait irq softirq steal
    //                          [guest guest_nice]   (kernel >= 2.6.24)
    std::array<int64_t, 10> vals{};
    int n = 0;
    for (int64_t v; n < 10 && (ss >> v); ++n) {
        vals[n] = v;
    }
    if (n < 4) {
        return false; // need at least user, nice, system, idle
    }

    const int64_t idle_val = vals[3] + (n > 4 ? vals[4] : 0); // idle + iowait
    int64_t total_val = 0;
    for (int i = 0; i < n; ++i) {
        total_val += vals[i];
    }
    out.idle  = idle_val;
    out.total = total_val;
    return true;
}

/// CPU-delta state kept between successive calls to collect_cpu_info /
/// collect_per_core_cpu.  Initialised to zero so the first call always
/// returns 0 % (a known "cold start" limitation that matches the Python probe).
struct PrevCpuState {
    int64_t sys_idle{0};
    int64_t sys_total{0};
    std::vector<int64_t> per_core_idle;
    std::vector<int64_t> per_core_total;
};

PrevCpuState g_prev{};

/// Build the list of per-core stat entries from /proc/stat.
/// Element 0 = aggregate "cpu" line, elements 1..N = "cpu0" .. "cpuN-1".
std::vector<StatLine> parse_all_stat(const std::string& content) {
    std::vector<StatLine> lines;
    std::istringstream ss(content);
    std::string line;
    while (std::getline(ss, line)) {
        if (line.empty() || line[0] != 'c') {
            break; // cpu lines are contiguous at the top
        }
        StatLine sl{};
        if (parse_stat_line(line, sl)) {
            lines.push_back(sl);
        }
    }
    return lines;
}

/// Detect platform heuristically.  Returns "jetson" if /etc/nv_tegra_release
/// exists, "rpi" if /proc/device-tree/model contains "Raspberry", else "linux".
std::string detect_platform() {
    // Jetson: nVidia Tegra release file
    {
        std::ifstream f("/etc/nv_tegra_release");
        if (f.good()) {
            return "jetson";
        }
    }
    // Raspberry Pi: device-tree model
    {
        std::string model;
        if (read_file("/proc/device-tree/model", model)) {
            if (model.find("Raspberry") != std::string::npos) {
                return "rpi";
            }
        }
    }
    return "linux";
}

/// Get hostname via POSIX gethostname (fallback to /proc/sys/kernel/hostname).
std::string get_hostname() {
    std::array<char, 256> buf{};
    if (gethostname(buf.data(), buf.size() - 1) == 0) {
        return std::string(buf.data());
    }
    // Fallback
    std::string host;
    if (read_file("/proc/sys/kernel/hostname", host)) {
        // Strip trailing newline
        while (!host.empty() && (host.back() == '\n' || host.back() == '\r')) {
            host.pop_back();
        }
        return host;
    }
    return "unknown";
}

/// Discover the first readable thermal zone temperature file path.
/// Scans /sys/class/thermal/thermal_zone*/temp in sorted order.
std::string discover_thermal_path() {
    const char* dir = "/sys/class/thermal";
    DIR* d = opendir(dir);
    if (!d) {
        return {};
    }
    std::string result;
    std::vector<std::string> entries;
    while (auto* ent = readdir(d)) {
        const std::string name(ent->d_name);
        if (name.find("thermal_zone") == 0) {
            entries.push_back(name);
        }
    }
    closedir(d);
    std::sort(entries.begin(), entries.end());

    for (const auto& e : entries) {
        std::string path = std::string(dir) + "/" + e + "/temp";
        std::ifstream fh(path);
        if (fh.good()) {
            result = path;
            break;
        }
    }
    return result;
}

/// Read CPU model name and core count from /proc/cpuinfo.
struct CpuMeta {
    std::string model_name;
    int cores{0};
    float freq_mhz{0.0f};
};

CpuMeta read_cpuinfo() {
    CpuMeta meta;
    std::string content;
    if (!read_file("/proc/cpuinfo", content)) {
        return meta;
    }

    std::istringstream ss(content);
    std::string line;
    bool found_model = false;
    while (std::getline(ss, line)) {
        // Count "processor" lines for core count.
        if (line.find("processor") == 0 && line.find(':') != std::string::npos) {
            ++meta.cores;
        }
        // "model name" or "Hardware" (ARM) for model string.
        if (!found_model) {
            if (line.find("model name") != std::string::npos ||
                line.find("Hardware") != std::string::npos) {
                auto pos = line.find(':');
                if (pos != std::string::npos) {
                    std::string val = line.substr(pos + 1);
                    // Trim leading whitespace
                    auto start = val.find_first_not_of(" \t");
                    if (start != std::string::npos) {
                        val = val.substr(start);
                    }
                    // Trim trailing whitespace / newline
                    while (!val.empty() && (val.back() == '\n' || val.back() == '\r' ||
                           val.back() == ' ' || val.back() == '\t')) {
                        val.pop_back();
                    }
                    if (!val.empty()) {
                        meta.model_name = val;
                        found_model = true;
                    }
                }
            }
        }
        // "cpu MHz" for frequency
        if (meta.freq_mhz == 0.0f && line.find("cpu MHz") != std::string::npos) {
            auto pos = line.find(':');
            if (pos != std::string::npos) {
                try {
                    meta.freq_mhz = std::stof(line.substr(pos + 1));
                } catch (...) {
                    // ignore parse errors
                }
            }
        }
    }
    return meta;
}

} // anonymous namespace

// ===========================================================================
// Public implementations
// ===========================================================================

MemoryInfo collect_memory_info() {
    MemoryInfo info{};
    std::string content;
    if (!read_file("/proc/meminfo", content)) {
        return info;
    }

    std::istringstream ss(content);
    std::string line;
    bool got_total = false;
    bool got_avail = false;

    while (std::getline(ss, line) && !(got_total && got_avail)) {
        if (line.compare(0, 9, "MemTotal:") == 0) {
            std::istringstream ls(line.substr(9));
            ls >> info.total_kb;
            got_total = true;
        } else if (line.compare(0, 13, "MemAvailable:") == 0) {
            std::istringstream ls(line.substr(13));
            ls >> info.available_kb;
            got_avail = true;
        }
    }

    if (info.total_kb > 0) {
        info.used_kb  = info.total_kb - info.available_kb;
        info.percent  = static_cast<float>(info.used_kb) /
                        static_cast<float>(info.total_kb) * 100.0f;
    }
    return info;
}

CpuInfo collect_cpu_info() {
    CpuInfo info{};
    CpuMeta meta = read_cpuinfo();
    info.model_name    = meta.model_name;
    info.cores         = meta.cores;
    info.frequency_mhz = meta.freq_mhz;

    // --- CPU utilisation via /proc/stat delta ---
    std::string content;
    if (!read_file("/proc/stat", content)) {
        return info; // return metadata only, percent stays 0
    }

    auto lines = parse_all_stat(content);
    if (lines.empty()) {
        return info;
    }

    // Element 0 is the aggregate "cpu" line.
    const auto& agg = lines[0];
    const int64_t d_idle  = agg.idle  - g_prev.sys_idle;
    const int64_t d_total = agg.total - g_prev.sys_total;
    if (d_total > 0) {
        info.percent = std::clamp(
            static_cast<float>(1.0 - static_cast<double>(d_idle) /
                             static_cast<double>(d_total)) * 100.0f,
            0.0f, 100.0f);
    }
    g_prev.sys_idle  = agg.idle;
    g_prev.sys_total = agg.total;

    // Also update per-core state so collect_per_core_cpu() stays in sync.
    g_prev.per_core_idle.clear();
    g_prev.per_core_total.clear();
    for (size_t i = 1; i < lines.size(); ++i) { // skip aggregate
        g_prev.per_core_idle.push_back(lines[i].idle);
        g_prev.per_core_total.push_back(lines[i].total);
    }

    return info;
}

std::vector<float> collect_per_core_cpu() {
    std::string content;
    if (!read_file("/proc/stat", content)) {
        return {};
    }

    auto lines = parse_all_stat(content);
    if (lines.size() < 2) {
        return {}; // need at least aggregate + one core
    }

    // Per-core lines start at index 1 (skip aggregate).
    const size_t num_cores = lines.size() - 1;

    // Ensure previous state vectors are sized correctly.
    if (g_prev.per_core_idle.size() != num_cores) {
        g_prev.per_core_idle.assign(num_cores, 0);
        g_prev.per_core_total.assign(num_cores, 0);
    }

    std::vector<float> percents;
    percents.reserve(num_cores);
    for (size_t i = 0; i < num_cores; ++i) {
        const auto& cur  = lines[i + 1];
        const int64_t d_idle  = cur.idle  - g_prev.per_core_idle[i];
        const int64_t d_total = cur.total - g_prev.per_core_total[i];
        float pct = 0.0f;
        if (d_total > 0) {
            pct = std::clamp(
                static_cast<float>(1.0 - static_cast<double>(d_idle) /
                                 static_cast<double>(d_total)) * 100.0f,
                0.0f, 100.0f);
        }
        percents.push_back(pct);
    }

    // Update previous state.
    for (size_t i = 0; i < num_cores; ++i) {
        g_prev.per_core_idle[i]  = lines[i + 1].idle;
        g_prev.per_core_total[i] = lines[i + 1].total;
    }
    // Also refresh aggregate so subsequent collect_cpu_info() stays consistent.
    if (!lines.empty()) {
        g_prev.sys_idle  = lines[0].idle;
        g_prev.sys_total = lines[0].total;
    }

    return percents;
}

float collect_temperature() {
    static const std::string thermal_path = discover_thermal_path();
    if (thermal_path.empty()) {
        return -1.0f;
    }

    std::string raw;
    if (!read_file(thermal_path.c_str(), raw)) {
        return -1.0f;
    }

    try {
        // Thermal zones report millidegrees Celsius.
        const int milli = std::stoi(raw);
        return static_cast<float>(milli) / 1000.0f;
    } catch (const std::exception&) {
        return -1.0f;
    }
}

SystemInfo collect_system_info() {
    SystemInfo sys{};

    sys.hostname = get_hostname();
    sys.platform = detect_platform();

    // Memory -- standalone, no delta dependency.
    sys.memory = collect_memory_info();

    // CPU -- updates the internal delta state.
    sys.cpu = collect_cpu_info();

    // Temperature.
    sys.temperature_c = collect_temperature();

    return sys;
}

} // namespace ai_edge
