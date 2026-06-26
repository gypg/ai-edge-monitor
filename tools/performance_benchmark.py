"""性能基准测试工具

提供以下功能：
1. micro-benchmark：测量各个组件的性能开销
2. 端到端性能测试：测量完整监控管线的性能
3. 资源使用分析：CPU、内存、磁盘使用情况
"""

from __future__ import annotations

import gc
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 添加项目路径
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@dataclass
class BenchmarkResult:
    """基准测试结果"""
    name: str
    duration_ms: float
    cpu_time_ms: float
    memory_delta_mb: float
    iterations: int
    avg_time_ms: float
    p95_time_ms: float
    p99_time_ms: float
    min_time_ms: float
    max_time_ms: float
    success: bool = True
    error_message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "cpu_time_ms": self.cpu_time_ms,
            "memory_delta_mb": self.memory_delta_mb,
            "iterations": self.iterations,
            "avg_time_ms": self.avg_time_ms,
            "p95_time_ms": self.p95_time_ms,
            "p99_time_ms": self.p99_time_ms,
            "min_time_ms": self.min_time_ms,
            "max_time_ms": self.max_time_ms,
            "success": self.success,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }


class PerformanceBenchmark:
    """性能基准测试工具"""
    
    def __init__(self, output_dir: str = "reports/benchmark"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.results: List[BenchmarkResult] = []
    
    def run_benchmark(
        self,
        name: str,
        func: callable,
        iterations: int = 100,
        warmup: int = 10,
        **kwargs
    ) -> BenchmarkResult:
        """运行基准测试"""
        print(f"Running benchmark: {name} ({iterations} iterations)")
        
        # 预热
        for _ in range(warmup):
            try:
                func(**kwargs)
            except Exception:
                pass
        
        # 收集垃圾
        gc.collect()
        
        # 测量内存
        memory_before = self._get_memory_usage()
        
        # 测量时间
        times = []
        start_time = time.perf_counter()
        start_cpu = time.process_time()
        
        for i in range(iterations):
            iter_start = time.perf_counter()
            try:
                func(**kwargs)
                iter_end = time.perf_counter()
                times.append((iter_end - iter_start) * 1000)
            except Exception as e:
                iter_end = time.perf_counter()
                times.append((iter_end - iter_start) * 1000)
                if i == 0:
                    return BenchmarkResult(
                        name=name,
                        duration_ms=0,
                        cpu_time_ms=0,
                        memory_delta_mb=0,
                        iterations=0,
                        avg_time_ms=0,
                        p95_time_ms=0,
                        p99_time_ms=0,
                        min_time_ms=0,
                        max_time_ms=0,
                        success=False,
                        error_message=str(e),
                    )
        
        end_time = time.perf_counter()
        end_cpu = time.process_time()
        memory_after = self._get_memory_usage()
        
        # 计算统计
        times.sort()
        duration_ms = (end_time - start_time) * 1000
        cpu_time_ms = (end_cpu - start_cpu) * 1000
        memory_delta = memory_after - memory_before
        
        result = BenchmarkResult(
            name=name,
            duration_ms=duration_ms,
            cpu_time_ms=cpu_time_ms,
            memory_delta_mb=memory_delta,
            iterations=iterations,
            avg_time_ms=sum(times) / len(times),
            p95_time_ms=times[int(len(times) * 0.95)],
            p99_time_ms=times[int(len(times) * 0.99)],
            min_time_ms=times[0],
            max_time_ms=times[-1],
        )
        
        self.results.append(result)
        print(f"  Completed: avg={result.avg_time_ms:.2f}ms, p95={result.p95_time_ms:.2f}ms")
        
        return result
    
    def _get_memory_usage(self) -> float:
        """获取当前内存使用（MB）"""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / (1024 * 1024)
        except ImportError:
            return 0.0
    
    def run_component_benchmarks(self) -> List[BenchmarkResult]:
        """运行组件级基准测试"""
        results = []
        
        # 1. 测试 DummyProbe
        from platform_adapter import DummyProbe
        probe = DummyProbe()
        results.append(self.run_benchmark(
            "DummyProbe.read_metrics",
            probe.read_metrics,
            iterations=1000,
        ))
        
        # 2. 测试 AggregatorAnalyzer
        from aggregator_analyzer import AggregatorAnalyzer
        analyzer = AggregatorAnalyzer()
        
        def ingest_sample():
            from platform_adapter import RawMetrics
            raw = RawMetrics(
                ts_ms=int(time.time() * 1000),
                cpu_percent=50.0,
                mem_used_mb=1000.0,
                mem_total_mb=4000.0,
                gpu_percent=None,
                gpu_mem_used_mb=None,
                temperature_c=60.0,
                probe_name="test",
                status="ok",
                latency_ms=0.1,
            )
            analyzer.ingest_metrics(raw)
        
        results.append(self.run_benchmark(
            "AggregatorAnalyzer.ingest_metrics",
            ingest_sample,
            iterations=1000,
        ))
        
        # 3. 测试 get_summary
        results.append(self.run_benchmark(
            "AggregatorAnalyzer.get_summary",
            analyzer.get_summary,
            iterations=100,
        ))
        
        return results
    
    def run_e2e_benchmark(self, duration_sec: int = 10) -> BenchmarkResult:
        """运行端到端基准测试"""
        from app_orchestrator import Orchestrator
        from config_manager import MonitorConfig
        
        config = MonitorConfig(
            duration_sec=duration_sec,
            interval_ms=100,
            output_dir=str(self.output_dir / "e2e_test"),
            force_dummy=True,
            exporters=("jsonl", "summary"),
        )
        
        def run_session():
            orchestrator = Orchestrator(config)
            return orchestrator.run()
        
        return self.run_benchmark(
            f"End-to-End ({duration_sec}s)",
            run_session,
            iterations=1,
            warmup=0,
        )
    
    def save_results(self, filename: str = "benchmark_results.json") -> Path:
        """保存测试结果"""
        output_path = self.output_dir / filename
        
        results_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": [r.to_dict() for r in self.results],
            "summary": self._generate_summary(),
        }
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results_data, f, indent=2, ensure_ascii=False)
        
        print(f"\nResults saved to: {output_path}")
        return output_path
    
    def _generate_summary(self) -> Dict[str, Any]:
        """生成测试摘要"""
        if not self.results:
            return {}
        
        successful = [r for r in self.results if r.success]
        failed = [r for r in self.results if not r.success]
        
        return {
            "total_benchmarks": len(self.results),
            "successful": len(successful),
            "failed": len(failed),
            "total_duration_ms": sum(r.duration_ms for r in self.results),
            "total_memory_delta_mb": sum(r.memory_delta_mb for r in self.results),
        }
    
    def print_summary(self) -> None:
        """打印测试摘要"""
        print("\n" + "=" * 60)
        print("Performance Benchmark Summary")
        print("=" * 60)
        
        for result in self.results:
            status = "✓" if result.success else "✗"
            print(f"\n{status} {result.name}")
            if result.success:
                print(f"  Iterations: {result.iterations}")
                print(f"  Avg: {result.avg_time_ms:.2f}ms")
                print(f"  P95: {result.p95_time_ms:.2f}ms")
                print(f"  P99: {result.p99_time_ms:.2f}ms")
                print(f"  Min: {result.min_time_ms:.2f}ms")
                print(f"  Max: {result.max_time_ms:.2f}ms")
                print(f"  Memory: {result.memory_delta_mb:.2f}MB")
            else:
                print(f"  Error: {result.error_message}")
        
        summary = self._generate_summary()
        print("\n" + "-" * 60)
        print(f"Total: {summary.get('total_benchmarks', 0)} benchmarks")
        print(f"Successful: {summary.get('successful', 0)}")
        print(f"Failed: {summary.get('failed', 0)}")
        print("=" * 60)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Performance Benchmark Tool")
    parser.add_argument("--output", default="reports/benchmark", help="Output directory")
    parser.add_argument("--e2e-duration", type=int, default=10, help="E2E test duration (seconds)")
    parser.add_argument("--skip-e2e", action="store_true", help="Skip E2E test")
    args = parser.parse_args()
    
    benchmark = PerformanceBenchmark(args.output)
    
    print("Starting performance benchmarks...\n")
    
    # 运行组件基准测试
    benchmark.run_component_benchmarks()
    
    # 运行 E2E 测试
    if not args.skip_e2e:
        benchmark.run_e2e_benchmark(args.e2e_duration)
    
    # 保存结果
    benchmark.save_results()
    
    # 打印摘要
    benchmark.print_summary()


if __name__ == "__main__":
    main()