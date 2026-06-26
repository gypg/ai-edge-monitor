#pragma once
/// @file gpu_tracker.h
/// Correlate CPU RSS with GPU memory changes to detect dual-channel leaks.

#include <cmath>
#include <deque>
#include <numeric>
#include <optional>
#include <tuple>
#include <vector>

namespace ai_hwmon {

struct GpuLeakAlert {
    enum class Pattern { DualLeak, CpuOnlyLeak, GpuOnlyLeak };
    enum class Severity { Critical, Warning };

    Pattern  pattern;
    Severity severity;
    bool     cpu_leak_detected;
    bool     gpu_leak_detected;
    double   cpu_slope;
    double   gpu_slope;
};

namespace detail {

inline double linear_slope(const std::vector<double>& values,
                           const std::vector<int64_t>& timestamps) {
    const auto n = values.size();
    if (n < 2) return 0.0;

    double sx = 0, sy = 0, sxy = 0, sx2 = 0;
    for (size_t i = 0; i < n; ++i) {
        const double x = static_cast<double>(timestamps[i]);
        sx  += x;
        sy  += values[i];
        sxy += x * values[i];
        sx2 += x * x;
    }
    const double denom = static_cast<double>(n) * sx2 - sx * sx;
    if (denom == 0.0) return 0.0;
    return (static_cast<double>(n) * sxy - sx * sy) / denom;
}

inline double r_squared(const std::vector<double>& values,
                        const std::vector<int64_t>& timestamps) {
    const auto n = values.size();
    if (n < 2) return 0.0;

    const double mean_y = std::accumulate(values.begin(), values.end(), 0.0)
                          / static_cast<double>(n);
    double ss_tot = 0.0;
    for (const auto& y : values) ss_tot += (y - mean_y) * (y - mean_y);
    if (ss_tot == 0.0) return 0.0;

    const double slope = linear_slope(values, timestamps);
    double sx_mean = 0.0;
    for (const auto& t : timestamps) sx_mean += static_cast<double>(t);
    sx_mean /= static_cast<double>(n);
    const double intercept = mean_y - slope * sx_mean;

    double ss_res = 0.0;
    for (size_t i = 0; i < n; ++i) {
        const double predicted = slope * static_cast<double>(timestamps[i]) + intercept;
        ss_res += (values[i] - predicted) * (values[i] - predicted);
    }
    return 1.0 - ss_res / ss_tot;
}

}  // namespace detail

/// GPU memory tracker that correlates CPU RSS with GPU memory.
class GpuMemoryTracker {
public:
    explicit GpuMemoryTracker(int window_size = 60,
                              double r_squared_threshold = 0.8,
                              double slope_threshold_mb_per_ms = 0.0001)
        : window_size_(window_size)
        , r_squared_threshold_(r_squared_threshold)
        , slope_threshold_(slope_threshold_mb_per_ms) {}

    std::optional<GpuLeakAlert> observe(double rss_mb,
                                        double gpu_mem_mb,
                                        int64_t timestamp_ms) {
        rss_values_.push_back(rss_mb);
        cpu_timestamps_.push_back(timestamp_ms);
        gpu_values_.push_back(gpu_mem_mb);
        gpu_timestamps_.push_back(timestamp_ms);

        trim(rss_values_);
        trim(cpu_timestamps_);
        trim(gpu_values_);
        trim(gpu_timestamps_);

        constexpr int kMinSamples = 5;
        if (static_cast<int>(rss_values_.size()) < kMinSamples) return std::nullopt;

        const bool cpu_leak = detect_trend(rss_values_, cpu_timestamps_);
        const bool gpu_leak = detect_trend(gpu_values_, gpu_timestamps_);

        auto cs = detail::linear_slope(
            std::vector<double>(rss_values_.begin(), rss_values_.end()),
            std::vector<int64_t>(cpu_timestamps_.begin(), cpu_timestamps_.end()));
        auto gs = detail::linear_slope(
            std::vector<double>(gpu_values_.begin(), gpu_values_.end()),
            std::vector<int64_t>(gpu_timestamps_.begin(), gpu_timestamps_.end()));

        if (cpu_leak && gpu_leak) {
            return GpuLeakAlert{
                GpuLeakAlert::Pattern::DualLeak,
                GpuLeakAlert::Severity::Critical,
                true, true, cs, gs};
        }
        if (cpu_leak) {
            return GpuLeakAlert{
                GpuLeakAlert::Pattern::CpuOnlyLeak,
                GpuLeakAlert::Severity::Warning,
                true, false, cs, gs};
        }
        if (gpu_leak) {
            return GpuLeakAlert{
                GpuLeakAlert::Pattern::GpuOnlyLeak,
                GpuLeakAlert::Severity::Warning,
                false, true, cs, gs};
        }
        return std::nullopt;
    }

private:
    template <typename Deque>
    void trim(Deque& d) {
        while (static_cast<int>(d.size()) > window_size_) d.pop_front();
    }

    bool detect_trend(const std::deque<double>& values,
                      const std::deque<int64_t>& timestamps) const {
        std::vector<double>   v(values.begin(), values.end());
        std::vector<int64_t>  t(timestamps.begin(), timestamps.end());
        const double r2    = detail::r_squared(v, t);
        const double slope = detail::linear_slope(v, t);
        return r2 >= r_squared_threshold_ && slope > slope_threshold_;
    }

    int window_size_;
    double r_squared_threshold_;
    double slope_threshold_;
    std::deque<double>   rss_values_;
    std::deque<double>   gpu_values_;
    std::deque<int64_t>  cpu_timestamps_;
    std::deque<int64_t>  gpu_timestamps_;
};

}  // namespace ai_hwmon
