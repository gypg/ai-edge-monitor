#include "include/memory_monitor.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unistd.h>

namespace ai_edge {

namespace {

// Trim whitespace from both ends of a string (immutable — returns new string).
std::string trim(const std::string& s) {
    const auto start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return {};
    const auto end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end - start + 1);
}

// Read a single "Field:  value kB" line from a /proc file and return the numeric value.
// Returns 0 if the field is not found or cannot be parsed.
uint64_t parse_proc_kb_field(std::istream& stream, const std::string& field_name) {
    std::string line;
    while (std::getline(stream, line)) {
        if (line.rfind(field_name + ":", 0) != 0) continue;

        // Skip the colon and whitespace to reach the numeric value.
        const auto colon_pos = line.find(':');
        if (colon_pos == std::string::npos) continue;

        const std::string rest = trim(line.substr(colon_pos + 1));
        // Value is in kB; extract the leading integer portion.
        std::istringstream value_stream(rest);
        uint64_t value = 0;
        value_stream >> value;
        return value;
    }
    return 0;
}

} // anonymous namespace

// ---------------------------------------------------------------------------
// Construction
// ---------------------------------------------------------------------------

MemoryMonitor::MemoryMonitor(int pid)
    : _pid(pid), _start_time_ms(_monotonic_ms()) {
    if (_pid == -1) {
        _pid = static_cast<int>(getpid());
    }
    _samples.reserve(64);  // Pre-allocate for typical leak-detection workloads.
}

// ---------------------------------------------------------------------------
// Current process memory (/proc/[pid]/status)
// ---------------------------------------------------------------------------

ProcessMemoryInfo MemoryMonitor::get_process_memory() const {
    // Build the /proc path.  Use /proc/self for the calling process.
    std::string proc_path;
    if (_pid == static_cast<int>(getpid())) {
        proc_path = "/proc/self/status";
    } else {
        proc_path = "/proc/" + std::to_string(_pid) + "/status";
    }

    std::ifstream status_file(proc_path);
    if (!status_file.is_open()) {
        throw std::runtime_error(
            "MemoryMonitor: cannot open " + proc_path +
            " (process may not exist or /proc is unavailable)");
    }

    ProcessMemoryInfo info{};
    info.pid = _pid;
    info.rss_kb  = parse_proc_kb_field(status_file, "VmRSS");
    info.vsize_kb = parse_proc_kb_field(status_file, "VmSize");
    info.shared_kb = parse_proc_kb_field(status_file, "VmStk");

    // Reset and re-read to also grab the process name.
    status_file.clear();
    status_file.seekg(0);
    std::string line;
    while (std::getline(status_file, line)) {
        if (line.rfind("Name:", 0) == 0) {
            info.name = trim(line.substr(line.find(':') + 1));
            break;
        }
    }

    return info;
}

// ---------------------------------------------------------------------------
// Sampling for leak detection
// ---------------------------------------------------------------------------

void MemoryMonitor::take_sample() {
    // Read from /proc/[pid]/statm for RSS and heap pages.
    std::string statm_path;
    if (_pid == static_cast<int>(getpid())) {
        statm_path = "/proc/self/statm";
    } else {
        statm_path = "/proc/" + std::to_string(_pid) + "/statm";
    }

    std::ifstream statm_file(statm_path);
    if (!statm_file.is_open()) {
        throw std::runtime_error(
            "MemoryMonitor: cannot open " + statm_path);
    }

    // /proc/[pid]/statm columns (in pages):
    //   size  resident  shared  text  lib  data  dt
    uint64_t size_pages = 0, resident_pages = 0, shared_pages = 0;
    uint64_t text_pages = 0, lib_pages = 0, data_pages = 0;
    statm_file >> size_pages >> resident_pages >> shared_pages
               >> text_pages >> lib_pages >> data_pages;

    // Page size is typically 4 KiB; read it at runtime for portability.
    const long page_size = sysconf(_SC_PAGESIZE);
    const uint64_t page_kb = (page_size > 0)
        ? static_cast<uint64_t>(page_size) / 1024
        : 4;  // Fallback: 4 KiB

    MemoryLeakSample sample{};
    sample.timestamp_ms = _monotonic_ms() - _start_time_ms;
    sample.rss_kb  = resident_pages * page_kb;
    sample.heap_kb = data_pages * page_kb;

    _samples.push_back(sample);
}

bool MemoryMonitor::detect_leak(float threshold_mb_per_min) const {
    // Need at least 2 data points to form a trend.
    if (_samples.size() < 2) return false;

    // Linear regression:  RSS = slope * t + intercept
    // We compute the slope of RSS (kB) with respect to time (ms).
    const size_t n = _samples.size();
    double sum_t = 0, sum_r = 0, sum_tt = 0, sum_tr = 0;

    for (size_t i = 0; i < n; ++i) {
        const double t = static_cast<double>(_samples[i].timestamp_ms);
        const double r = static_cast<double>(_samples[i].rss_kb);
        sum_t  += t;
        sum_r  += r;
        sum_tt += t * t;
        sum_tr += t * r;
    }

    const double denom = static_cast<double>(n) * sum_tt - sum_t * sum_t;
    if (std::fabs(denom) < 1e-9) {
        // All timestamps identical — cannot determine slope.
        return false;
    }

    const double slope_kb_per_ms =
        (static_cast<double>(n) * sum_tr - sum_t * sum_r) / denom;

    // Convert slope from kB/ms to MB/min:
    //   (kB/ms) * (1 MB / 1024 kB) * (60 000 ms / 1 min)
    const double slope_mb_per_min = slope_kb_per_ms * 60000.0 / 1024.0;

    return slope_mb_per_min > static_cast<double>(threshold_mb_per_min);
}

const std::vector<MemoryLeakSample>& MemoryMonitor::get_samples() const {
    return _samples;
}

void MemoryMonitor::clear_samples() {
    _samples.clear();
    _start_time_ms = _monotonic_ms();
}

// ---------------------------------------------------------------------------
// System-wide memory (/proc/meminfo)
// ---------------------------------------------------------------------------

uint64_t MemoryMonitor::get_system_total_kb() {
    std::ifstream meminfo("/proc/meminfo");
    if (!meminfo.is_open()) {
        throw std::runtime_error(
            "MemoryMonitor: cannot open /proc/meminfo");
    }
    return parse_proc_kb_field(meminfo, "MemTotal");
}

uint64_t MemoryMonitor::get_system_available_kb() {
    // Prefer MemAvailable (kernel 3.14+); fall back to MemFree + Buffers + Cached.
    std::ifstream meminfo("/proc/meminfo");
    if (!meminfo.is_open()) {
        throw std::runtime_error(
            "MemoryMonitor: cannot open /proc/meminfo");
    }

    const uint64_t available = parse_proc_kb_field(meminfo, "MemAvailable");
    if (available > 0) return available;

    // Fallback for older kernels.
    meminfo.clear();
    meminfo.seekg(0);
    const uint64_t mem_free  = parse_proc_kb_field(meminfo, "MemFree");
    meminfo.clear();
    meminfo.seekg(0);
    const uint64_t buffers  = parse_proc_kb_field(meminfo, "Buffers");
    meminfo.clear();
    meminfo.seekg(0);
    const uint64_t cached   = parse_proc_kb_field(meminfo, "Cached");
    return mem_free + buffers + cached;
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

uint64_t MemoryMonitor::_read_proc_field(const std::string& field) const {
    std::string proc_path;
    if (_pid == static_cast<int>(getpid())) {
        proc_path = "/proc/self/status";
    } else {
        proc_path = "/proc/" + std::to_string(_pid) + "/status";
    }

    std::ifstream f(proc_path);
    if (!f.is_open()) return 0;
    return parse_proc_kb_field(f, field);
}

uint64_t MemoryMonitor::_monotonic_ms() {
    using namespace std::chrono;
    return static_cast<uint64_t>(
        duration_cast<milliseconds>(
            steady_clock::now().time_since_epoch()
        ).count()
    );
}

} // namespace ai_edge
