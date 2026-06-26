#pragma once
/**
 * optimized_kernels.hpp
 * High-performance numerical kernels for AI hardware monitoring.
 *
 * Provides SIMD-accelerated (NEON / AVX2) statistics, moving average,
 * and anomaly-detection routines used for latency and FPS analysis on
 * embedded platforms.  Every function has a scalar fallback so the code
 * compiles and runs correctly on any architecture.
 */

#include <cstddef>
#include <cstdint>
#include <vector>

namespace ai_edge {

// ---------------------------------------------------------------------------
// Descriptive statistics on a contiguous float array.
// Used for latency / FPS / power-analysis pipelines.
// ---------------------------------------------------------------------------
struct StatsResult {
    float mean;
    float std_dev;
    float min_val;
    float max_val;
    float p50;  // median (50th percentile)
    float p95;  // 95th percentile
    float p99;  // 99th percentile
};

/// Compute descriptive statistics over @p count elements starting at @p data.
/// @pre  data != nullptr && count > 0
StatsResult compute_stats(const float* data, size_t count);

// ---------------------------------------------------------------------------
// Moving average — exponential / sliding-window smoother for metric streams.
// ---------------------------------------------------------------------------
/// Write a simple moving average of @p input into @p output using a window
/// of @p window elements.  The first (window-1) elements use a partial
/// (shrinking) window so the output array has the same length as the input.
/// @pre  input != nullptr && output != nullptr && window > 0 && window <= count
void moving_average(const float* input, float* output, size_t count,
                    size_t window);

// ---------------------------------------------------------------------------
// Z-score anomaly detection.
// ---------------------------------------------------------------------------
struct AnomalyResult {
    size_t index;
    float value;
    float z_score;
};

/// Detect points whose z-score exceeds @p threshold (default 3.0).
/// Returns a (possibly empty) vector of {index, value, z_score} tuples.
/// @pre  data != nullptr && count >= 2
std::vector<AnomalyResult> detect_anomalies_zscore(const float* data,
                                                    size_t count,
                                                    float threshold = 3.0f);

// ---------------------------------------------------------------------------
// Runtime SIMD feature queries.
// ---------------------------------------------------------------------------
/// True if ARM NEON intrinsics are available at runtime.
bool has_neon_support();

/// True if x86 AVX2 intrinsics are available at runtime.
bool has_avx2_support();

// ---------------------------------------------------------------------------
// Micro-benchmark wrapper for compute_stats.
// ---------------------------------------------------------------------------
struct BenchmarkResult {
    StatsResult stats;
    double elapsed_us;   // wall-clock microseconds
    size_t elements;
    bool used_simd;      // true when a SIMD path was taken
};

/// Run compute_stats @p iterations times and report timing / SIMD status.
/// @pre  data != nullptr && count > 0 && iterations > 0
BenchmarkResult benchmark_stats(const float* data, size_t count,
                                int iterations = 100);

}  // namespace ai_edge
