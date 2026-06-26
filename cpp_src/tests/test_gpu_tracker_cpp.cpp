/// @file test_gpu_tracker_cpp.cpp
/// Unit tests for ai_hwmon::GpuMemoryTracker (header-only library).

#include <cassert>
#include <cstdio>
#include <optional>
#include <vector>

#include "gpu_tracker.h"

// ---------------------------------------------------------------------------
// Shared globals from test_main.cpp
// ---------------------------------------------------------------------------
extern int g_passed;
extern int g_failed;

struct TestEntry {
    const char* name;
    int (*fn)();
};
extern std::vector<TestEntry>& tests;

#define TEST(name)                                                    \
    static int test_##name();                                         \
    static struct Register_##name {                                   \
        Register_##name() { tests.push_back({#name, test_##name}); } \
    } reg_##name;                                                     \
    static int test_##name()

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static std::vector<double> make_rising(double start, double step, int count) {
    std::vector<double> v;
    v.reserve(count);
    for (int i = 0; i < count; ++i) v.push_back(start + step * i);
    return v;
}

static std::vector<double> make_constant(double val, int count) {
    return std::vector<double>(count, val);
}

static std::vector<int64_t> make_timestamps(int count, int64_t interval_ms = 1000) {
    std::vector<int64_t> ts;
    ts.reserve(count);
    for (int i = 0; i < count; ++i) ts.push_back(i * interval_ms);
    return ts;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

TEST(gpu_tracker_dual_leak_critical) {
    ai_hwmon::GpuMemoryTracker tracker(60, 0.8, 0.0001);
    auto rss_vals = make_rising(100.0, 1.0, 20);
    auto gpu_vals = make_rising(200.0, 0.5, 20);
    auto ts       = make_timestamps(20);

    std::optional<ai_hwmon::GpuLeakAlert> alert;
    for (int i = 0; i < 20; ++i) {
        alert = tracker.observe(rss_vals[i], gpu_vals[i], ts[i]);
    }
    assert(alert.has_value());
    assert(alert->pattern == ai_hwmon::GpuLeakAlert::Pattern::DualLeak);
    assert(alert->severity == ai_hwmon::GpuLeakAlert::Severity::Critical);
    assert(alert->cpu_leak_detected);
    assert(alert->gpu_leak_detected);
    assert(alert->cpu_slope > 0.0);
    assert(alert->gpu_slope > 0.0);
    return 0;
}

TEST(gpu_tracker_cpu_only_leak) {
    ai_hwmon::GpuMemoryTracker tracker(60, 0.8, 0.0001);
    auto rss_vals = make_rising(100.0, 1.0, 20);
    auto gpu_vals = make_constant(512.0, 20);
    auto ts       = make_timestamps(20);

    std::optional<ai_hwmon::GpuLeakAlert> alert;
    for (int i = 0; i < 20; ++i) {
        alert = tracker.observe(rss_vals[i], gpu_vals[i], ts[i]);
    }
    assert(alert.has_value());
    assert(alert->pattern == ai_hwmon::GpuLeakAlert::Pattern::CpuOnlyLeak);
    assert(alert->severity == ai_hwmon::GpuLeakAlert::Severity::Warning);
    assert(alert->cpu_leak_detected);
    assert(!alert->gpu_leak_detected);
    return 0;
}

TEST(gpu_tracker_gpu_only_leak) {
    ai_hwmon::GpuMemoryTracker tracker(60, 0.8, 0.0001);
    auto rss_vals = make_constant(100.0, 20);
    auto gpu_vals = make_rising(200.0, 0.5, 20);
    auto ts       = make_timestamps(20);

    std::optional<ai_hwmon::GpuLeakAlert> alert;
    for (int i = 0; i < 20; ++i) {
        alert = tracker.observe(rss_vals[i], gpu_vals[i], ts[i]);
    }
    assert(alert.has_value());
    assert(alert->pattern == ai_hwmon::GpuLeakAlert::Pattern::GpuOnlyLeak);
    assert(alert->severity == ai_hwmon::GpuLeakAlert::Severity::Warning);
    assert(!alert->cpu_leak_detected);
    assert(alert->gpu_leak_detected);
    return 0;
}

TEST(gpu_tracker_no_leak) {
    ai_hwmon::GpuMemoryTracker tracker(60, 0.8, 0.0001);
    auto rss_vals = make_constant(100.0, 20);
    auto gpu_vals = make_constant(512.0, 20);
    auto ts       = make_timestamps(20);

    std::optional<ai_hwmon::GpuLeakAlert> alert;
    for (int i = 0; i < 20; ++i) {
        alert = tracker.observe(rss_vals[i], gpu_vals[i], ts[i]);
    }
    assert(!alert.has_value());
    return 0;
}

TEST(gpu_tracker_insufficient_data) {
    ai_hwmon::GpuMemoryTracker tracker(60, 0.8, 0.0001);
    // Feed fewer than _MIN_SAMPLES (5) observations
    for (int count = 0; count < 5; ++count) {
        ai_hwmon::GpuMemoryTracker sub(60, 0.8, 0.0001);
        std::optional<ai_hwmon::GpuLeakAlert> alert;
        for (int i = 0; i < count; ++i) {
            alert = sub.observe(100.0 + 10.0 * i, 200.0 + 10.0 * i,
                                static_cast<int64_t>(i) * 1000);
        }
        assert(!alert.has_value());
    }
    return 0;
}

TEST(gpu_tracker_exactly_five_can_detect) {
    ai_hwmon::GpuMemoryTracker tracker(60, 0.3, 0.0001);
    auto rss_vals = make_rising(100.0, 10.0, 5);
    auto gpu_vals = make_rising(200.0, 10.0, 5);
    auto ts       = make_timestamps(5);

    std::optional<ai_hwmon::GpuLeakAlert> alert;
    for (int i = 0; i < 5; ++i) {
        alert = tracker.observe(rss_vals[i], gpu_vals[i], ts[i]);
    }
    assert(alert.has_value());
    assert(alert->severity == ai_hwmon::GpuLeakAlert::Severity::Critical);
    return 0;
}

TEST(gpu_tracker_large_window_no_crash) {
    ai_hwmon::GpuMemoryTracker tracker(1000, 0.8, 0.0001);
    for (int i = 0; i < 5000; ++i) {
        tracker.observe(100.0 + (i % 100), 200.0 + (i % 50),
                        static_cast<int64_t>(i) * 100);
    }
    // Just verify no crash with large data volumes.
    return 0;
}
