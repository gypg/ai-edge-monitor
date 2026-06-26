#pragma once
/// @file leak_detector.h
/// RSS-based memory leak detector using sliding-window linear regression.

#include <cmath>
#include <deque>
#include <optional>
#include <tuple>
#include <vector>

namespace ai_hwmon {

struct LeakAlert {
    int    target_pid;
    double r_squared;
    double slope_mb_per_sec;
    double estimated_time_to_oom;   // seconds, -1.0 when unavailable
    int64_t window_start_ms;
    int64_t window_end_ms;
    int    sample_count;
};

namespace detail {

/// Pure linear regression returning (slope, intercept, r_squared).
inline std::tuple<double, double, double>
linear_regression(const std::vector<double>& xs,
                  const std::vector<double>& ys) {
    const auto n = static_cast<double>(xs.size());
    if (n < 2) return {0.0, 0.0, 0.0};

    double sum_x = 0, sum_y = 0, sum_xx = 0, sum_xy = 0;
    for (size_t i = 0; i < xs.size(); ++i) {
        sum_x  += xs[i];
        sum_y  += ys[i];
        sum_xx += xs[i] * xs[i];
        sum_xy += xs[i] * ys[i];
    }

    const double denom = n * sum_xx - sum_x * sum_x;
    if (denom == 0.0) return {0.0, 0.0, 0.0};

    const double slope     = (n * sum_xy - sum_x * sum_y) / denom;
    const double intercept = (sum_y - slope * sum_x) / n;

    const double y_mean = sum_y / n;
    double ss_tot = 0.0, ss_res = 0.0;
    for (size_t i = 0; i < xs.size(); ++i) {
        ss_tot += (ys[i] - y_mean) * (ys[i] - y_mean);
        const double predicted = slope * xs[i] + intercept;
        ss_res += (ys[i] - predicted) * (ys[i] - predicted);
    }
    const double r_sq = (ss_tot > 0.0) ? (1.0 - ss_res / ss_tot) : 0.0;

    return {slope, intercept, r_sq};
}

}  // namespace detail

/// Sliding-window leak detector.
class LeakDetector {
public:
    explicit LeakDetector(int window_size = 60,
                          double r_squared_threshold = 0.8,
                          double slope_threshold_mb_per_sec = 0.1)
        : window_size_(window_size)
        , r_squared_threshold_(r_squared_threshold)
        , slope_threshold_(slope_threshold_mb_per_sec) {}

    /// Record a new RSS observation.  Returns an alert when a leak is detected.
    std::optional<LeakAlert> observe(double rss_mb, int64_t timestamp_ms) {
        observations_.emplace_back(timestamp_ms, rss_mb);
        if (static_cast<int>(observations_.size()) > window_size_) {
            observations_.pop_front();
        }
        if (observations_.size() < 2) return std::nullopt;

        const int64_t first_ts = observations_.front().first;
        std::vector<double> xs, ys;
        xs.reserve(observations_.size());
        ys.reserve(observations_.size());
        for (const auto& [ts, rss] : observations_) {
            xs.push_back(static_cast<double>(ts - first_ts) / 1000.0);
            ys.push_back(rss);
        }

        auto [slope, intercept, r_sq] = detail::linear_regression(xs, ys);

        if (r_sq <= r_squared_threshold_) return std::nullopt;
        if (slope <= slope_threshold_)     return std::nullopt;

        constexpr double kOomLimitMb = 2048.0;
        const double current_rss = ys.back();
        double tto = -1.0;
        if (slope > 0.0 && current_rss < kOomLimitMb) {
            tto = (kOomLimitMb - current_rss) / slope;
        }

        return LeakAlert{
            0,
            r_sq,
            slope,
            tto,
            observations_.front().first,
            observations_.back().first,
            static_cast<int>(observations_.size()),
        };
    }

private:
    int window_size_;
    double r_squared_threshold_;
    double slope_threshold_;
    std::deque<std::pair<int64_t, double>> observations_;
};

}  // namespace ai_hwmon
