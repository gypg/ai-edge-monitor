/** Simple assert-based test runner for ai_edge_native.
 *
 * No external test framework required.  Every test function returns 0 on
 * success and non-zero on failure; the runner reports the total at the end.
 *
 * Usage:
 *   cmake -B build && cmake --build build && ctest --test-dir build --output-on-failure
 *   -- or --
 *   ./build/tests/test_ai_edge
 */

#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "system_info.hpp"
#include "memory_monitor.hpp"
#include "optimized_kernels.hpp"

using namespace ai_edge;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

int g_passed = 0;
int g_failed = 0;

#define TEST(name)                                                    \
    static int test_##name();                                         \
    static struct Register_##name {                                   \
        Register_##name() { tests.push_back({#name, test_##name}); } \
    } reg_##name;                                                     \
    static int test_##name()

struct TestEntry {
    const char* name;
    int (*fn)();
};

// Non-static so companion test files (test_leak_detector_cpp.cpp, etc.) can
// register their tests via the same vector.
std::vector<TestEntry>& tests = *new std::vector<TestEntry>();

#define ASSERT_TRUE(expr)                                                    \
    do {                                                                     \
        if (!(expr)) {                                                       \
            std::fprintf(stderr, "  FAIL  %s:%d: %s\n", __FILE__, __LINE__, \
                         #expr);                                             \
            return 1;                                                        \
        }                                                                    \
    } while (0)

#define ASSERT_EQ(a, b) ASSERT_TRUE((a) == (b))
#define ASSERT_NE(a, b) ASSERT_TRUE((a) != (b))
#define ASSERT_GT(a, b) ASSERT_TRUE((a) > (b))
#define ASSERT_GE(a, b) ASSERT_TRUE((a) >= (b))
#define ASSERT_NEAR(a, b, tol) ASSERT_TRUE(std::fabs((a) - (b)) <= (tol))

// ---------------------------------------------------------------------------
// system_info tests
// ---------------------------------------------------------------------------

TEST(system_info_returns_nonempty_host) {
    auto info = collect_system_info();
    ASSERT_TRUE(!info.hostname.empty());
    return 0;
}

TEST(system_info_returns_positive_cpu_cores) {
    auto info = collect_system_info();
    ASSERT_GT(info.cpu.cores, 0);
    return 0;
}

TEST(system_info_returns_nonnegative_total_memory) {
    auto info = collect_system_info();
    ASSERT_GE(info.memory.total_kb, 0u);
    return 0;
}

TEST(system_info_has_platform_string) {
    auto info = collect_system_info();
    ASSERT_TRUE(!info.platform.empty());
    return 0;
}

// ---------------------------------------------------------------------------
// memory_monitor tests
// ---------------------------------------------------------------------------

TEST(memory_monitor_constructs) {
    MemoryMonitor mm;
    (void)mm;
    return 0;
}

TEST(memory_monitor_get_process_memory) {
    MemoryMonitor mm;
    auto info = mm.get_process_memory();
    ASSERT_GE(info.rss_kb, 0u);
    return 0;
}

TEST(memory_monitor_take_sample) {
    MemoryMonitor mm;
    mm.take_sample();
    auto& samples = mm.get_samples();
    ASSERT_EQ(samples.size(), 1u);
    return 0;
}

TEST(memory_monitor_detect_leak) {
    MemoryMonitor mm;
    // Feed a few samples so detect_leak has data to work with.
    for (int i = 0; i < 5; ++i) {
        mm.take_sample();
    }
    bool leaked = mm.detect_leak();
    // We only care that the call succeeds; the boolean value depends on
    // actual memory patterns which we cannot control in a unit test.
    (void)leaked;
    return 0;
}

TEST(memory_monitor_system_memory) {
    uint64_t total = MemoryMonitor::get_system_total_kb();
    uint64_t avail = MemoryMonitor::get_system_available_kb();
    ASSERT_GT(total, 0u);
    ASSERT_GE(avail, 0u);
    ASSERT_GE(total, avail);
    return 0;
}

// ---------------------------------------------------------------------------
// optimized_kernels tests
// ---------------------------------------------------------------------------

TEST(compute_stats_single_value) {
    float v[] = {42.0f};
    auto stats = compute_stats(v, 1);
    ASSERT_NEAR(stats.mean, 42.0, 1e-5);
    ASSERT_NEAR(stats.std_dev, 0.0, 1e-5);
    ASSERT_NEAR(stats.min_val, 42.0, 1e-5);
    ASSERT_NEAR(stats.max_val, 42.0, 1e-5);
    return 0;
}

TEST(compute_stats_known_values) {
    float v[] = {2.0f, 4.0f, 4.0f, 4.0f, 5.0f, 5.0f, 7.0f, 9.0f};
    auto stats = compute_stats(v, 8);
    ASSERT_NEAR(stats.mean, 5.0, 1e-5);
    ASSERT_NEAR(stats.min_val, 2.0, 1e-5);
    ASSERT_NEAR(stats.max_val, 9.0, 1e-5);
    // stddev of the sample: sqrt(4) = 2.0
    ASSERT_NEAR(stats.std_dev, 2.0, 0.2);
    return 0;
}

TEST(compute_stats_percentiles) {
    // 100 values 1..100
    std::vector<float> v(100);
    for (size_t i = 0; i < 100; ++i) v[i] = static_cast<float>(i + 1);
    auto stats = compute_stats(v.data(), v.size());
    ASSERT_NEAR(stats.mean, 50.5, 1e-3);
    ASSERT_NEAR(stats.p50, 50.0, 2.0);  // approximate
    ASSERT_NEAR(stats.p95, 95.0, 2.0);
    ASSERT_NEAR(stats.p99, 99.0, 2.0);
    return 0;
}

TEST(detect_anomalies_zscore_no_anomalies) {
    // All identical values -> z-scores are 0 -> no anomalies.
    std::vector<float> v(20, 5.0f);
    auto anomalies = detect_anomalies_zscore(v.data(), v.size(), 3.0f);
    ASSERT_TRUE(anomalies.empty());
    return 0;
}

TEST(detect_anomalies_zscore_finds_outlier) {
    float v[] = {1, 1, 1, 1, 1, 1, 1, 1, 1, 100};
    auto anomalies = detect_anomalies_zscore(v, 10, 2.0f);
    ASSERT_TRUE(!anomalies.empty());
    // The outlier at index 9 should be flagged.
    bool found = false;
    for (auto& a : anomalies) {
        if (a.index == 9) {
            found = true;
            break;
        }
    }
    ASSERT_TRUE(found);
    return 0;
}

TEST(moving_average_basic) {
    float input[] = {1.0f, 2.0f, 3.0f, 4.0f, 5.0f};
    float output[5] = {};
    moving_average(input, output, 5, 3);
    // After a window of 3: avg(1,2,3)=2, avg(2,3,4)=3, avg(3,4,5)=4
    ASSERT_NEAR(output[2], 2.0, 1e-5);
    ASSERT_NEAR(output[3], 3.0, 1e-5);
    ASSERT_NEAR(output[4], 4.0, 1e-5);
    return 0;
}

TEST(has_neon_support_returns_bool) {
    bool result = has_neon_support();
    // Just verify it does not crash; value depends on the host.
    (void)result;
    return 0;
}

TEST(has_avx2_support_returns_bool) {
    bool result = has_avx2_support();
    (void)result;
    return 0;
}

TEST(benchmark_stats_runs) {
    std::vector<float> v(100);
    for (size_t i = 0; i < 100; ++i) v[i] = static_cast<float>(i);
    auto result = benchmark_stats(v.data(), v.size(), 10);
    ASSERT_GT(result.elapsed_us, 0.0);
    ASSERT_EQ(result.elements, 100u);
    return 0;
}

// ---------------------------------------------------------------------------
// Main runner
// ---------------------------------------------------------------------------

int main() {
    std::printf("=== ai_edge_native test runner ===\n");
    for (auto& t : tests) {
        std::printf("[RUN ] %s\n", t.name);
        int rc = t.fn();
        if (rc == 0) {
            std::printf("[PASS] %s\n", t.name);
            ++g_passed;
        } else {
            std::printf("[FAIL] %s (exit %d)\n", t.name, rc);
            ++g_failed;
        }
    }
    std::printf("\n=== Results: %d passed, %d failed, %d total ===\n", g_passed,
                g_failed, g_passed + g_failed);
    return g_failed > 0 ? 1 : 0;
}
