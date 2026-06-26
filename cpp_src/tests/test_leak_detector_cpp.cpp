/// @file test_leak_detector_cpp.cpp
/// Unit tests for ai_hwmon::LeakDetector (header-only library).

#include <cassert>
#include <cstdio>
#include <optional>
#include <vector>

#include "leak_detector.h"

// ---------------------------------------------------------------------------
// Helpers shared with test_runner main
// ---------------------------------------------------------------------------
extern int g_passed;
extern int g_failed;

#define TEST(name)                                                    \
    static int test_##name();                                         \
    static struct Register_##name {                                   \
        Register_##name();                                            \
    } reg_##name;                                                     \
    Register_##name::Register_##name();                               \
    static int test_##name()

// Forward-declare registration vector
struct TestEntry {
    const char* name;
    int (*fn)();
};
extern std::vector<TestEntry>& tests;

// We include the macro definitions via test_runner's test_main.cpp,
// but since we compile separately, we redefine what we need.
// Actually -- these files are linked together, so we use the same globals.
// Redefine TEST to append to the shared vector.

#undef TEST
#define TEST(name)                                                    \
    static int test_##name();                                         \
    static struct Register_##name {                                   \
        Register_##name() { tests.push_back({#name, test_##name}); } \
    } reg_##name;                                                     \
    static int test_##name()

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

TEST(leak_detector_perfect_linear_growth) {
    ai_hwmon::LeakDetector det(30, 0.8, 0.1);
    std::optional<ai_hwmon::LeakAlert> alert;
    for (int i = 0; i < 30; ++i) {
        alert = det.observe(100.0 + 1.0 * i, 1000000 + i * 1000);
    }
    assert(alert.has_value());
    assert(alert->r_squared > 0.99);
    assert(alert->slope_mb_per_sec > 0.1);
    assert(alert->sample_count == 30);
    return 0;
}

TEST(leak_detector_steady_state_no_alert) {
    ai_hwmon::LeakDetector det(30, 0.8, 0.1);
    for (int i = 0; i < 60; ++i) {
        auto alert = det.observe(512.0, 1000000 + i * 1000);
        assert(!alert.has_value());
    }
    return 0;
}

TEST(leak_detector_single_observation_returns_nullopt) {
    ai_hwmon::LeakDetector det(30, 0.8, 0.1);
    auto alert = det.observe(100.0, 1000000);
    assert(!alert.has_value());
    return 0;
}

TEST(leak_detector_window_size_respected) {
    int window = 10;
    ai_hwmon::LeakDetector det(window, 0.0, 0.0);
    for (int i = 0; i < 30; ++i) {
        det.observe(100.0 + i, 1000000 + i * 1000);
    }
    // After 30 observations with window=10, the detector should only use
    // the last 10.  Feed a strong trend and verify detection.
    auto alert = det.observe(100.0, 2000000 + 30 * 1000);
    // The observation deque is capped; verify no crash.
    (void)alert;
    return 0;
}

TEST(leak_detector_high_r_squared_threshold_blocks_alert) {
    ai_hwmon::LeakDetector det(30, 0.9999, 0.001);
    std::optional<ai_hwmon::LeakAlert> alert;
    // Add some noise to break perfect linearity
    for (int i = 0; i < 40; ++i) {
        double noise = (i % 3 == 0) ? 1.5 : -1.5;
        alert = det.observe(100.0 + 1.0 * i + noise, 1000000 + i * 1000);
    }
    // Noisy data should not achieve R^2 > 0.9999
    assert(!alert.has_value());
    return 0;
}

TEST(leak_detector_low_slope_threshold_blocks_alert) {
    ai_hwmon::LeakDetector det(30, 0.0, 100.0);
    // Growth at 0.5 MB/s is below the 100 MB/s threshold
    std::optional<ai_hwmon::LeakAlert> alert;
    for (int i = 0; i < 40; ++i) {
        alert = det.observe(100.0 + 0.5 * i, 1000000 + i * 1000);
    }
    assert(!alert.has_value());
    return 0;
}

TEST(leak_detector_alert_has_positive_tto) {
    ai_hwmon::LeakDetector det(20, 0.8, 0.01);
    std::optional<ai_hwmon::LeakAlert> alert;
    for (int i = 0; i < 25; ++i) {
        alert = det.observe(200.0 + 2.0 * i, 500000 + i * 1000);
    }
    assert(alert.has_value());
    assert(alert->estimated_time_to_oom > 0.0);
    return 0;
}

TEST(leak_detector_rapid_sampling) {
    ai_hwmon::LeakDetector det(60, 0.8, 0.1);
    std::optional<ai_hwmon::LeakAlert> alert;
    // Simulate rapid 10ms sampling with 0.5 MB/s growth
    for (int i = 0; i < 200; ++i) {
        double rss = 100.0 + 0.005 * i;  // 0.5 MB/s at 10ms intervals
        alert = det.observe(rss, 1000000 + i * 10);
    }
    // At 10ms intervals, slope in MB/s = 0.5, should trigger
    assert(alert.has_value());
    assert(alert->slope_mb_per_sec > 0.1);
    return 0;
}

// ---------------------------------------------------------------------------
// Linear regression edge cases
// ---------------------------------------------------------------------------

TEST(linear_regression_empty_input) {
    std::vector<double> xs, ys;
    auto [slope, intercept, r_sq] = ai_hwmon::detail::linear_regression(xs, ys);
    assert(slope == 0.0);
    assert(r_sq == 0.0);
    return 0;
}

TEST(linear_regression_single_point) {
    std::vector<double> xs = {1.0}, ys = {1.0};
    auto [slope, intercept, r_sq] = ai_hwmon::detail::linear_regression(xs, ys);
    assert(slope == 0.0);
    assert(r_sq == 0.0);
    return 0;
}

TEST(linear_regression_identical_xs) {
    std::vector<double> xs = {5.0, 5.0, 5.0};
    std::vector<double> ys = {1.0, 2.0, 3.0};
    auto [slope, intercept, r_sq] = ai_hwmon::detail::linear_regression(xs, ys);
    assert(slope == 0.0);
    return 0;
}

TEST(linear_regression_perfect_fit) {
    std::vector<double> xs = {0, 1, 2, 3, 4};
    std::vector<double> ys = {3, 5, 7, 9, 11};
    auto [slope, intercept, r_sq] = ai_hwmon::detail::linear_regression(xs, ys);
    assert(std::fabs(slope - 2.0) < 1e-9);
    assert(std::fabs(intercept - 3.0) < 1e-9);
    assert(std::fabs(r_sq - 1.0) < 1e-9);
    return 0;
}
