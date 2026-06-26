/**
 * optimized_kernels.cpp
 * =====================
 * SIMD-accelerated numerical kernels for embedded AI hardware monitoring.
 *
 * Compilation targets:
 *   - x86-64  : scalar fallback  +  AVX2 path   (gcc/clang -mavx2, or MSVC /arch:AVX2)
 *   - AArch64 : scalar fallback  +  NEON path    (always-on on AArch64; arm_neon.h)
 *   - Other   : scalar fallback only
 *
 * Runtime detection reads /proc/cpuinfo on Linux; on other OSes the SIMD
 * queries return false unless the compile-time flag is active.
 *
 * Strategy for every function:
 *   1. Compile-time guard  (#if defined(__AVX2__) / __ARM_NEON)
 *   2. Runtime guard       (has_avx2_support() / has_neon_support())
 *   3. Scalar fallback     (plain C++ loop)
 */

#include "include/optimized_kernels.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <numeric>
#include <string>

// ── Platform-specific SIMD headers ──────────────────────────────────────────
#if defined(__AVX2__)
    #include <immintrin.h>   // AVX2 intrinsics
#endif

#if defined(__ARM_NEON) || defined(__ARM_NEON__)
    #include <arm_neon.h>    // ARM NEON intrinsics
#endif

namespace ai_edge {

// ═══════════════════════════════════════════════════════════════════════════
// Runtime SIMD detection
// ═══════════════════════════════════════════════════════════════════════════

/// Scan /proc/cpuinfo for a given feature flag (case-sensitive substring).
static bool cpuinfo_has_flag(const char* flag) {
    std::ifstream cpuinfo("/proc/cpuinfo");
    if (!cpuinfo.is_open()) {
        return false;
    }
    std::string line;
    while (std::getline(cpuinfo, line)) {
        // "Features" on ARM, "flags" on x86 — both contain the feature tokens.
        if (line.find("Features") != std::string::npos ||
            line.find("flags") != std::string::npos) {
            if (line.find(flag) != std::string::npos) {
                return true;
            }
        }
    }
    return false;
}

bool has_neon_support() {
#if defined(__ARM_NEON) || defined(__ARM_NEON__)
    // Compile-time NEON is enabled; confirm runtime capability as well.
    return cpuinfo_has_flag("neon");
#else
    return false;
#endif
}

bool has_avx2_support() {
#if defined(__AVX2__)
    // Compile-time AVX2 enabled; confirm runtime capability.
    return cpuinfo_has_flag("avx2");
#else
    return false;
#endif
}

// ═══════════════════════════════════════════════════════════════════════════
// compute_stats  —  mean, std-dev, min, max, p50, p95, p99
// ═══════════════════════════════════════════════════════════════════════════

/// Scalar reduction: single-pass for mean/min/max, second pass for variance,
/// then a partial sort for percentiles.
static StatsResult compute_stats_scalar(const float* data, size_t count) {
    // --- Pass 1: accumulate sum, min, max ---
    float sum = 0.0f;
    float mn  = data[0];
    float mx  = data[0];
    for (size_t i = 0; i < count; ++i) {
        sum += data[i];
        mn = std::min(mn, data[i]);
        mx = std::max(mx, data[i]);
    }
    const float mean = sum / static_cast<float>(count);

    // --- Pass 2: variance ---
    float var_sum = 0.0f;
    for (size_t i = 0; i < count; ++i) {
        float d = data[i] - mean;
        var_sum += d * d;
    }
    const float std_dev = std::sqrt(var_sum / static_cast<float>(count));

    // --- Percentiles via partial copies ---
    std::vector<float> sorted(data, data + count);
    std::sort(sorted.begin(), sorted.end());

    auto percentile = [&](float pct) -> float {
        float idx = pct * static_cast<float>(count - 1);
        size_t lo = static_cast<size_t>(idx);
        size_t hi = std::min(lo + 1, count - 1);
        float frac = idx - static_cast<float>(lo);
        return sorted[lo] * (1.0f - frac) + sorted[hi] * frac;
    };

    return {mean, std_dev, mn, mx, percentile(0.50f), percentile(0.95f),
            percentile(0.99f)};
}

#if defined(__AVX2__)

/// AVX2-accelerated summation with horizontal reduce.
/// Falls back to scalar for the tail elements.
static float avx2_sum(const float* data, size_t count) {
    __m256 vsum = _mm256_setzero_ps();
    size_t i = 0;
    // Process 8 floats at a time.
    for (; i + 8 <= count; i += 8) {
        __m256 v = _mm256_loadu_ps(data + i);
        vsum = _mm256_add_ps(vsum, v);
    }
    // Horizontal sum of the 8-lane vector.
    __m128 hi  = _mm256_extractf128_ps(vsum, 1);
    __m128 lo  = _mm256_castps256_ps128(vsum);
    __m128 sum = _mm_add_ps(lo, hi);       // 4 elements
    sum = _mm_hadd_ps(sum, sum);           // 2 elements
    sum = _mm_hadd_ps(sum, sum);           // 1 element
    float result;
    _mm_store_ss(&result, sum);
    // Tail elements (scalar).
    for (; i < count; ++i) {
        result += data[i];
    }
    return result;
}

/// AVX2-accelerated min reduction.
static float avx2_min(const float* data, size_t count) {
    __m256 vmin = _mm256_broadcast_ss(&data[0]);
    size_t i = 0;
    for (; i + 8 <= count; i += 8) {
        __m256 v = _mm256_loadu_ps(data + i);
        vmin = _mm256_min_ps(vmin, v);
    }
    // Horizontal min across the 8-lane vector.
    __m128 hi  = _mm256_extractf128_ps(vmin, 1);
    __m128 lo  = _mm256_castps256_ps128(vmin);
    __m128 mn  = _mm_min_ps(lo, hi);
    // Reduce 4 → 1 with shuffles.
    mn = _mm_min_ps(mn, _mm_movehdup_ps(mn));
    mn = _mm_min_ps(mn, _mm_movehl_ps(mn, mn));
    float result;
    _mm_store_ss(&result, mn);
    for (; i < count; ++i) {
        result = std::min(result, data[i]);
    }
    return result;
}

/// AVX2-accelerated max reduction.
static float avx2_max(const float* data, size_t count) {
    __m256 vmax = _mm256_broadcast_ss(&data[0]);
    size_t i = 0;
    for (; i + 8 <= count; i += 8) {
        __m256 v = _mm256_loadu_ps(data + i);
        vmax = _mm256_max_ps(vmax, v);
    }
    __m128 hi  = _mm256_extractf128_ps(vmax, 1);
    __m128 lo  = _mm256_castps256_ps128(vmax);
    __m128 mx  = _mm_max_ps(lo, hi);
    mx = _mm_max_ps(mx, _mm_movehdup_ps(mx));
    mx = _mm_max_ps(mx, _mm_movehl_ps(mx, mx));
    float result;
    _mm_store_ss(&result, mx);
    for (; i < count; ++i) {
        result = std::max(result, data[i]);
    }
    return result;
}

/// AVX2-accelerated variance: two-pass with SIMD summation helpers.
static float avx2_variance(const float* data, size_t count, float mean) {
    __m256 vmean = _mm256_broadcast_ss(&mean);
    __m256 vsum  = _mm256_setzero_ps();
    size_t i = 0;
    for (; i + 8 <= count; i += 8) {
        __m256 v  = _mm256_loadu_ps(data + i);
        __m256 d  = _mm256_sub_ps(v, vmean);      // (x - mean)
        __m256 d2 = _mm256_mul_ps(d, d);           // (x - mean)^2
        vsum = _mm256_add_ps(vsum, d2);
    }
    // Horizontal sum.
    __m128 hi  = _mm256_extractf128_ps(vsum, 1);
    __m128 lo  = _mm256_castps256_ps128(vsum);
    __m128 sum = _mm_add_ps(lo, hi);
    sum = _mm_hadd_ps(sum, sum);
    sum = _mm_hadd_ps(sum, sum);
    float var_sum;
    _mm_store_ss(&var_sum, sum);
    for (; i < count; ++i) {
        float d = data[i] - mean;
        var_sum += d * d;
    }
    return var_sum;
}

/// Combined AVX2 stats (mean, std-dev, min, max via SIMD; percentiles scalar).
static StatsResult compute_stats_avx2(const float* data, size_t count) {
    float sum = avx2_sum(data, count);
    float mean = sum / static_cast<float>(count);
    float var_sum = avx2_variance(data, count, mean);
    float std_dev = std::sqrt(var_sum / static_cast<float>(count));
    float mn = avx2_min(data, count);
    float mx = avx2_max(data, count);

    // Percentiles still require a full sort — no shortcut.
    std::vector<float> sorted(data, data + count);
    std::sort(sorted.begin(), sorted.end());
    auto percentile = [&](float pct) -> float {
        float idx = pct * static_cast<float>(count - 1);
        size_t lo = static_cast<size_t>(idx);
        size_t hi = std::min(lo + 1, count - 1);
        float frac = idx - static_cast<float>(lo);
        return sorted[lo] * (1.0f - frac) + sorted[hi] * frac;
    };
    return {mean, std_dev, mn, mx, percentile(0.50f), percentile(0.95f),
            percentile(0.99f)};
}
#endif  // __AVX2__

#if defined(__ARM_NEON) || defined(__ARM_NEON__)

/// NEON-accelerated summation: 4 floats per vector register.
static float neon_sum(const float* data, size_t count) {
    float32x4_t vsum = vdupq_n_f32(0.0f);
    size_t i = 0;
    for (; i + 4 <= count; i += 4) {
        float32x4_t v = vld1q_f32(data + i);
        vsum = vaddq_f32(vsum, v);
    }
    // Horizontal sum: pairwise reduce 4 → 1.
    float32x2_t pair = vadd_f32(vget_low_f32(vsum), vget_high_f32(vsum));
    float result = vget_lane_f32(pair, 0) + vget_lane_f32(pair, 1);
    for (; i < count; ++i) {
        result += data[i];
    }
    return result;
}

/// NEON-accelerated min reduction.
static float neon_min(const float* data, size_t count) {
    float32x4_t vmin = vld1q_f32(data);
    size_t i = 0;
    // If count < 4, broadcast the first element.
    if (count < 4) {
        vmin = vdupq_n_f32(data[0]);
    } else {
        vmin = vld1q_f32(data);
        i = 4;
    }
    for (; i + 4 <= count; i += 4) {
        float32x4_t v = vld1q_f32(data + i);
        vmin = vminq_f32(vmin, v);
    }
    // Horizontal min.
    float32x2_t pair = vpmin_f32(vget_low_f32(vmin), vget_high_f32(vmin));
    float result = vget_lane_f32(pair, 0);
    if (vget_lane_f32(pair, 1) < result) {
        result = vget_lane_f32(pair, 1);
    }
    for (; i < count; ++i) {
        result = std::min(result, data[i]);
    }
    return result;
}

/// NEON-accelerated max reduction.
static float neon_max(const float* data, size_t count) {
    float32x4_t vmax;
    size_t i = 0;
    if (count < 4) {
        vmax = vdupq_n_f32(data[0]);
    } else {
        vmax = vld1q_f32(data);
        i = 4;
    }
    for (; i + 4 <= count; i += 4) {
        float32x4_t v = vld1q_f32(data + i);
        vmax = vmaxq_f32(vmax, v);
    }
    float32x2_t pair = vpmax_f32(vget_low_f32(vmax), vget_high_f32(vmax));
    float result = vget_lane_f32(pair, 0);
    if (vget_lane_f32(pair, 1) > result) {
        result = vget_lane_f32(pair, 1);
    }
    for (; i < count; ++i) {
        result = std::max(result, data[i]);
    }
    return result;
}

/// NEON variance: two-pass with SIMD dot-product-like accumulation.
static float neon_variance(const float* data, size_t count, float mean) {
    float32x4_t vmean = vdupq_n_f32(mean);
    float32x4_t vsum  = vdupq_n_f32(0.0f);
    size_t i = 0;
    for (; i + 4 <= count; i += 4) {
        float32x4_t v  = vld1q_f32(data + i);
        float32x4_t d  = vsubq_f32(v, vmean);
        float32x4_t d2 = vmulq_f32(d, d);
        vsum = vaddq_f32(vsum, d2);
    }
    float32x2_t pair = vadd_f32(vget_low_f32(vsum), vget_high_f32(vsum));
    float var_sum = vget_lane_f32(pair, 0) + vget_lane_f32(pair, 1);
    for (; i < count; ++i) {
        float d = data[i] - mean;
        var_sum += d * d;
    }
    return var_sum;
}

/// Combined NEON stats.
static StatsResult compute_stats_neon(const float* data, size_t count) {
    float sum = neon_sum(data, count);
    float mean = sum / static_cast<float>(count);
    float var_sum = neon_variance(data, count, mean);
    float std_dev = std::sqrt(var_sum / static_cast<float>(count));
    float mn = neon_min(data, count);
    float mx = neon_max(data, count);

    std::vector<float> sorted(data, data + count);
    std::sort(sorted.begin(), sorted.end());
    auto percentile = [&](float pct) -> float {
        float idx = pct * static_cast<float>(count - 1);
        size_t lo = static_cast<size_t>(idx);
        size_t hi = std::min(lo + 1, count - 1);
        float frac = idx - static_cast<float>(lo);
        return sorted[lo] * (1.0f - frac) + sorted[hi] * frac;
    };
    return {mean, std_dev, mn, mx, percentile(0.50f), percentile(0.95f),
            percentile(0.99f)};
}
#endif  // __ARM_NEON

StatsResult compute_stats(const float* data, size_t count) {
    if (count == 0) {
        return {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
    }

#if defined(__AVX2__)
    if (has_avx2_support()) {
        return compute_stats_avx2(data, count);
    }
#elif defined(__ARM_NEON) || defined(__ARM_NEON__)
    if (has_neon_support()) {
        return compute_stats_neon(data, count);
    }
#endif

    return compute_stats_scalar(data, count);
}

// ═══════════════════════════════════════════════════════════════════════════
// moving_average  —  simple sliding-window average
// ═══════════════════════════════════════════════════════════════════════════

void moving_average(const float* input, float* output, size_t count,
                    size_t window) {
    if (count == 0 || window == 0) {
        return;
    }

    // Seed: compute the sum of the first window (or fewer) elements.
    float running_sum = 0.0f;
    for (size_t i = 0; i < std::min(window, count); ++i) {
        running_sum += input[i];
        output[i] = running_sum / static_cast<float>(i + 1);
    }

    // Slide the window across the rest.
    for (size_t i = window; i < count; ++i) {
        running_sum += input[i] - input[i - window];
        output[i] = running_sum / static_cast<float>(window);
    }
}

// ═══════════════════════════════════════════════════════════════════════════
// detect_anomalies_zscore  —  flag points where |z| > threshold
// ═══════════════════════════════════════════════════════════════════════════

std::vector<AnomalyResult> detect_anomalies_zscore(const float* data,
                                                    size_t count,
                                                    float threshold) {
    std::vector<AnomalyResult> anomalies;
    if (count < 2) {
        return anomalies;
    }

    // Use compute_stats for mean and std_dev (leverages SIMD internally).
    StatsResult stats = compute_stats(data, count);

    if (stats.std_dev < 1e-9f) {
        // All values are essentially identical — no anomalies possible.
        return anomalies;
    }

    const float inv_std = 1.0f / stats.std_dev;
    for (size_t i = 0; i < count; ++i) {
        float z = (data[i] - stats.mean) * inv_std;
        if (std::fabs(z) > threshold) {
            anomalies.push_back({i, data[i], z});
        }
    }
    return anomalies;
}

// ═══════════════════════════════════════════════════════════════════════════
// benchmark_stats  —  micro-benchmark with timing and SIMD reporting
// ═══════════════════════════════════════════════════════════════════════════

BenchmarkResult benchmark_stats(const float* data, size_t count,
                                int iterations) {
    BenchmarkResult result{};
    result.elements = count;

    // Determine whether a SIMD path will be taken.
#if defined(__AVX2__)
    result.used_simd = has_avx2_support();
#elif defined(__ARM_NEON) || defined(__ARM_NEON__)
    result.used_simd = has_neon_support();
#else
    result.used_simd = false;
#endif

    // Warm-up pass (not timed).
    result.stats = compute_stats(data, count);

    // Timed passes.
    auto t0 = std::chrono::high_resolution_clock::now();
    for (int i = 0; i < iterations; ++i) {
        result.stats = compute_stats(data, count);
    }
    auto t1 = std::chrono::high_resolution_clock::now();

    result.elapsed_us =
        std::chrono::duration<double, std::micro>(t1 - t0).count() /
        static_cast<double>(iterations);

    return result;
}

}  // namespace ai_edge
