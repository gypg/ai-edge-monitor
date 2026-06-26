/**
 * pybind11 bindings for ai_edge_native.
 *
 * Exposes the C++ layer to Python as the ``_native_collector`` module so that
 * ``src/native_collector/__init__.py`` can import it transparently.
 *
 * Build:
 *   cmake -DBUILD_PYTHON=ON -B build && cmake --build build
 *   # or via pip / setuptools integration
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "system_info.hpp"
#include "memory_monitor.hpp"
#include "optimized_kernels.hpp"

namespace py = pybind11;
using namespace ai_edge;

PYBIND11_MODULE(ai_edge_native_py, m) {
    m.doc() = "High-performance native collectors for AI hardware monitoring";

    // -----------------------------------------------------------------------
    // system_info
    // -----------------------------------------------------------------------

    py::class_<CpuInfo>(m, "CpuInfo")
        .def_readonly("percent", &CpuInfo::percent)
        .def_readonly("frequency_mhz", &CpuInfo::frequency_mhz)
        .def_readonly("cores", &CpuInfo::cores)
        .def_readonly("model_name", &CpuInfo::model_name);

    py::class_<MemoryInfo>(m, "MemoryInfo")
        .def_readonly("total_kb", &MemoryInfo::total_kb)
        .def_readonly("used_kb", &MemoryInfo::used_kb)
        .def_readonly("available_kb", &MemoryInfo::available_kb)
        .def_readonly("percent", &MemoryInfo::percent);

    py::class_<SystemInfo>(m, "SystemInfo")
        .def_readonly("cpu", &SystemInfo::cpu)
        .def_readonly("memory", &SystemInfo::memory)
        .def_readonly("temperature_c", &SystemInfo::temperature_c)
        .def_readonly("hostname", &SystemInfo::hostname)
        .def_readonly("platform", &SystemInfo::platform)
        .def("to_dict", [](const SystemInfo& self) -> py::dict {
            py::dict d;
            d["hostname"]   = self.hostname;
            d["platform"]   = self.platform;
            d["temperature_c"] = self.temperature_c;
            d["cpu_percent"]   = self.cpu.percent;
            d["cpu_frequency_mhz"] = self.cpu.frequency_mhz;
            d["cpu_cores"]     = self.cpu.cores;
            d["cpu_model_name"] = self.cpu.model_name;
            d["mem_total_mb"]  = self.memory.total_kb / 1024.0;
            d["mem_used_mb"]   = self.memory.used_kb / 1024.0;
            d["mem_available_mb"] = self.memory.available_kb / 1024.0;
            d["mem_percent"]   = self.memory.percent;
            return d;
        });

    m.def("collect_system_info", &collect_system_info,
          "Collect a full system snapshot (CPU, memory, temperature, identity).");
    m.def("collect_per_core_cpu", &collect_per_core_cpu,
          "Return per-core CPU percentages.");
    m.def("collect_memory_info", &collect_memory_info,
          "Read memory info from /proc/meminfo.");
    m.def("collect_cpu_info", &collect_cpu_info,
          "Read CPU info from /proc/stat and /proc/cpuinfo.");
    m.def("collect_temperature", &collect_temperature,
          "Read SoC / CPU temperature in Celsius.");

    // -----------------------------------------------------------------------
    // memory_monitor
    // -----------------------------------------------------------------------

    py::class_<ProcessMemoryInfo>(m, "ProcessMemoryInfo")
        .def_readonly("pid", &ProcessMemoryInfo::pid)
        .def_readonly("name", &ProcessMemoryInfo::name)
        .def_readonly("rss_kb", &ProcessMemoryInfo::rss_kb)
        .def_readonly("vsize_kb", &ProcessMemoryInfo::vsize_kb)
        .def_readonly("shared_kb", &ProcessMemoryInfo::shared_kb);

    py::class_<MemoryLeakSample>(m, "MemoryLeakSample")
        .def_readonly("timestamp_ms", &MemoryLeakSample::timestamp_ms)
        .def_readonly("rss_kb", &MemoryLeakSample::rss_kb)
        .def_readonly("heap_kb", &MemoryLeakSample::heap_kb);

    py::class_<MemoryMonitor>(m, "MemoryMonitor")
        .def(py::init<int>(), py::arg("pid") = -1,
             "Create a MemoryMonitor. pid=-1 monitors the current process.")
        .def("get_process_memory", &MemoryMonitor::get_process_memory,
             "Get current process memory usage.")
        .def("take_sample", &MemoryMonitor::take_sample,
             "Record an RSS sample for leak detection.")
        .def("detect_leak", &MemoryMonitor::detect_leak,
             py::arg("threshold_mb_per_min") = 1.0f,
             "Detect memory leak based on collected samples.")
        .def("get_samples", &MemoryMonitor::get_samples,
             "Return collected memory leak samples.",
             py::return_value_policy::reference_internal)
        .def("clear_samples", &MemoryMonitor::clear_samples,
             "Clear all collected samples.")
        .def_static("get_system_total_kb", &MemoryMonitor::get_system_total_kb,
                    "System total memory in KB.")
        .def_static("get_system_available_kb", &MemoryMonitor::get_system_available_kb,
                    "System available memory in KB.");

    // -----------------------------------------------------------------------
    // optimized_kernels
    // -----------------------------------------------------------------------

    py::class_<StatsResult>(m, "StatsResult")
        .def_readonly("mean", &StatsResult::mean)
        .def_readonly("std_dev", &StatsResult::std_dev)
        .def_readonly("min_val", &StatsResult::min_val)
        .def_readonly("max_val", &StatsResult::max_val)
        .def_readonly("p50", &StatsResult::p50)
        .def_readonly("p95", &StatsResult::p95)
        .def_readonly("p99", &StatsResult::p99)
        .def("to_dict", [](const StatsResult& self) -> py::dict {
            py::dict d;
            d["mean"]    = self.mean;
            d["std_dev"] = self.std_dev;
            d["min_val"] = self.min_val;
            d["max_val"] = self.max_val;
            d["p50"]     = self.p50;
            d["p95"]     = self.p95;
            d["p99"]     = self.p99;
            return d;
        });

    py::class_<AnomalyResult>(m, "AnomalyResult")
        .def_readonly("index", &AnomalyResult::index)
        .def_readonly("value", &AnomalyResult::value)
        .def_readonly("z_score", &AnomalyResult::z_score);

    py::class_<BenchmarkResult>(m, "BenchmarkResult")
        .def_readonly("stats", &BenchmarkResult::stats)
        .def_readonly("elapsed_us", &BenchmarkResult::elapsed_us)
        .def_readonly("elements", &BenchmarkResult::elements)
        .def_readonly("used_simd", &BenchmarkResult::used_simd);

    m.def("compute_stats",
          [](const std::vector<float>& data) -> StatsResult {
              if (data.empty()) {
                  return StatsResult{0, 0, 0, 0, 0, 0, 0};
              }
              return compute_stats(data.data(), data.size());
          },
          py::arg("data"),
          "Compute descriptive statistics (mean, stddev, percentiles) over a "
          "vector of floats.");

    m.def("moving_average",
          [](const std::vector<float>& input, size_t window) {
              std::vector<float> output(input.size());
              moving_average(input.data(), output.data(), input.size(), window);
              return output;
          },
          py::arg("input"), py::arg("window"),
          "Compute a simple moving average with the given window size.");

    m.def("detect_anomalies_zscore",
          [](const std::vector<float>& data, float threshold) {
              if (data.size() < 2) {
                  return std::vector<AnomalyResult>{};
              }
              return detect_anomalies_zscore(data.data(), data.size(), threshold);
          },
          py::arg("data"), py::arg("threshold") = 3.0f,
          "Detect anomalies whose z-score exceeds the given threshold.");

    m.def("has_neon_support", &has_neon_support,
          "True if ARM NEON intrinsics are available at runtime.");
    m.def("has_avx2_support", &has_avx2_support,
          "True if x86 AVX2 intrinsics are available at runtime.");

    m.def("benchmark_stats",
          [](const std::vector<float>& data, int iterations) {
              if (data.empty()) {
                  return BenchmarkResult{
                      StatsResult{0, 0, 0, 0, 0, 0, 0}, 0.0, 0, false};
              }
              return benchmark_stats(data.data(), data.size(), iterations);
          },
          py::arg("data"), py::arg("iterations") = 100,
          "Benchmark compute_stats with timing and SIMD detection.");
}
