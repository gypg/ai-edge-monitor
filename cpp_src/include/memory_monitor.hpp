#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace ai_edge {

struct ProcessMemoryInfo {
    int pid;
    std::string name;
    uint64_t rss_kb;       // Resident Set Size
    uint64_t vsize_kb;     // Virtual Size
    uint64_t shared_kb;    // Shared memory
};

struct MemoryLeakSample {
    uint64_t timestamp_ms;
    uint64_t rss_kb;
    uint64_t heap_kb;
};

class MemoryMonitor {
public:
    explicit MemoryMonitor(int pid = -1);  // -1 = self

    // Current memory usage
    ProcessMemoryInfo get_process_memory() const;

    // RSS over time for leak detection
    void take_sample();
    bool detect_leak(float threshold_mb_per_min = 1.0f) const;
    const std::vector<MemoryLeakSample>& get_samples() const;
    void clear_samples();

    // System-wide memory
    static uint64_t get_system_total_kb();
    static uint64_t get_system_available_kb();

private:
    int _pid;
    std::vector<MemoryLeakSample> _samples;
    uint64_t _start_time_ms;

    uint64_t _read_proc_field(const std::string& field) const;
    static uint64_t _monotonic_ms();
};

} // namespace ai_edge
