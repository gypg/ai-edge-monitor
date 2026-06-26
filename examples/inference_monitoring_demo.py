"""视觉推理任务监控示例

展示如何使用 ai-edge-monitor 监控视觉推理任务的性能，
包括 CPU/GPU 利用率、内存使用、功耗等关键指标。

典型使用场景：
1. TensorRT/ONNX Runtime 推理优化验证
2. 多线程推理性能分析
3. 长时间推理任务稳定性监控
4. 功耗与热管理优化

使用方法：
1. 终端 1: ai-edge-monitor run --duration 300 --out reports/inference_optimization
2. 终端 2: python examples/inference_monitoring_demo.py --duration 300
3. 查看报告: reports/inference_optimization/report.png
"""

from __future__ import annotations

import argparse
import math
import random
import time
from typing import List, Optional, Tuple


class VisualInferenceWorkload:
    """模拟视觉推理工作负载
    
    模拟典型视觉推理任务的计算模式：
    - 图像预处理（CPU 密集）
    - 模型推理（GPU 密集，这里用 CPU 模拟）
    - 后处理（CPU 密集）
    - 结果序列化（I/O 密集）
    """
    
    def __init__(self, 
                 image_size: Tuple[int, int] = (640, 480),
                 batch_size: int = 1,
                 model_complexity: str = "medium"):
        self.image_size = image_size
        self.batch_size = batch_size
        self.model_complexity = model_complexity
        
        # 根据模型复杂度调整计算量
        self.complexity_factor = {
            "light": 0.5,
            "medium": 1.0,
            "heavy": 2.0
        }.get(model_complexity, 1.0)
        
        # 性能统计
        self.total_frames = 0
        self.total_inference_time = 0.0
        self.preprocess_time = 0.0
        self.postprocess_time = 0.0
        
    def simulate_frame(self) -> float:
        """模拟单帧推理，返回推理时间（秒）"""
        start_time = time.perf_counter()
        
        # 1. 图像预处理（CPU 密集）
        preprocess_start = time.perf_counter()
        self._simulate_preprocess()
        preprocess_end = time.perf_counter()
        self.preprocess_time += preprocess_end - preprocess_start
        
        # 2. 模型推理（模拟 GPU 计算）
        inference_start = time.perf_counter()
        self._simulate_inference()
        inference_end = time.perf_counter()
        
        # 3. 后处理
        postprocess_start = time.perf_counter()
        self._simulate_postprocess()
        postprocess_end = time.perf_counter()
        self.postprocess_time += postprocess_end - postprocess_start
        
        # 更新统计
        frame_time = time.perf_counter() - start_time
        self.total_frames += 1
        self.total_inference_time += frame_time
        
        return frame_time
    
    def _simulate_preprocess(self):
        """模拟图像预处理：resize、归一化、数据布局转换"""
        width, height = self.image_size
        pixel_count = width * height * 3  # RGB
        
        # 模拟 resize 操作
        resize_ops = int(pixel_count * 0.3 * self.complexity_factor)
        for _ in range(resize_ops // 100):
            math.sin(random.random())
        
        # 模拟归一化
        normalize_ops = int(pixel_count * 0.1 * self.complexity_factor)
        for _ in range(normalize_ops // 100):
            math.cos(random.random())
    
    def _simulate_inference(self):
        """模拟模型推理：卷积、全连接等操作"""
        # 根据模型复杂度模拟不同计算量
        if self.model_complexity == "light":
            ops = 50000
        elif self.model_complexity == "medium":
            ops = 200000
        else:  # heavy
            ops = 500000
        
        ops = int(ops * self.complexity_factor)
        
        # 模拟矩阵运算
        for _ in range(ops // 1000):
            a = random.random()
            b = random.random()
            math.sqrt(a * a + b * b)
    
    def _simulate_postprocess(self):
        """模拟后处理：NMS、坐标转换、结果编码"""
        # 模拟 NMS 操作
        nms_ops = 1000 * self.complexity_factor
        for _ in range(int(nms_ops)):
            math.exp(-random.random())
        
        # 模拟结果序列化
        serialization_ops = 500 * self.complexity_factor
        for _ in range(int(serialization_ops)):
            str(random.randint(0, 1000))
    
    def get_stats(self) -> dict:
        """获取性能统计"""
        if self.total_frames == 0:
            return {}
        
        avg_inference_time = self.total_inference_time / self.total_frames
        fps = 1.0 / avg_inference_time if avg_inference_time > 0 else 0
        
        return {
            "total_frames": self.total_frames,
            "total_time_sec": self.total_inference_time,
            "avg_inference_time_ms": avg_inference_time * 1000,
            "fps": fps,
            "preprocess_ratio": self.preprocess_time / self.total_inference_time,
            "postprocess_ratio": self.postprocess_time / self.total_inference_time,
            "model_complexity": self.model_complexity,
            "image_size": self.image_size,
            "batch_size": self.batch_size,
        }


def run_inference_monitoring_demo(
    duration_sec: int = 60,
    image_size: Tuple[int, int] = (640, 480),
    batch_size: int = 1,
    model_complexity: str = "medium",
    target_fps: Optional[float] = None,
    progress_interval_sec: int = 5,
) -> dict:
    """运行视觉推理监控演示
    
    Args:
        duration_sec: 运行时长（秒）
        image_size: 图像尺寸 (width, height)
        batch_size: 批处理大小
        model_complexity: 模型复杂度 (light/medium/heavy)
        target_fps: 目标帧率，用于性能评估
        progress_interval_sec: 进度打印间隔
    
    Returns:
        性能统计字典
    """
    print(f"启动视觉推理监控演示:")
    print(f"  图像尺寸: {image_size[0]}x{image_size[1]}")
    print(f"  批处理大小: {batch_size}")
    print(f"  模型复杂度: {model_complexity}")
    print(f"  目标时长: {duration_sec}秒")
    if target_fps:
        print(f"  目标帧率: {target_fps} FPS")
    print()
    
    # 创建工作负载
    workload = VisualInferenceWorkload(
        image_size=image_size,
        batch_size=batch_size,
        model_complexity=model_complexity,
    )
    
    # 运行推理循环
    start_time = time.monotonic()
    next_progress = start_time
    frame_times: List[float] = []
    
    while True:
        now = time.monotonic()
        elapsed = now - start_time
        
        if elapsed >= duration_sec:
            break
        
        # 模拟单帧推理
        frame_time = workload.simulate_frame()
        frame_times.append(frame_time)
        
        # 打印进度
        if now >= next_progress:
            stats = workload.get_stats()
            current_fps = stats.get("fps", 0)
            fps_status = ""
            if target_fps:
                if current_fps >= target_fps:
                    fps_status = f" ✓ 达标 (目标: {target_fps})"
                else:
                    fps_status = f" ✗ 未达标 (目标: {target_fps})"
            
            print(
                f"[{elapsed:6.1f}s] 帧数: {stats['total_frames']:4d} | "
                f"FPS: {current_fps:6.1f}{fps_status} | "
                f"平均推理时间: {stats['avg_inference_time_ms']:6.2f}ms",
                flush=True,
            )
            next_progress = now + progress_interval_sec
    
    # 获取最终统计
    final_stats = workload.get_stats()
    
    # 计算性能分析
    if frame_times:
        avg_frame_time = sum(frame_times) / len(frame_times)
        min_frame_time = min(frame_times)
        max_frame_time = max(frame_times)
        
        # 计算 P95 帧时间
        sorted_times = sorted(frame_times)
        p95_index = int(len(sorted_times) * 0.95)
        p95_frame_time = sorted_times[p95_index] if p95_index < len(sorted_times) else max_frame_time
        
        final_stats.update({
            "min_frame_time_ms": min_frame_time * 1000,
            "max_frame_time_ms": max_frame_time * 1000,
            "p95_frame_time_ms": p95_frame_time * 1000,
            "frame_time_std_ms": math.sqrt(
                sum((t - avg_frame_time) ** 2 for t in frame_times) / len(frame_times)
            ) * 1000,
        })
    
    # 性能评估
    final_stats["performance_analysis"] = analyze_performance(final_stats, target_fps)
    
    return final_stats


def analyze_performance(stats: dict, target_fps: Optional[float] = None) -> dict:
    """分析性能瓶颈并提供优化建议"""
    analysis = {
        "bottlenecks": [],
        "optimization_suggestions": [],
        "overall_rating": "good",
    }
    
    fps = stats.get("fps", 0)
    preprocess_ratio = stats.get("preprocess_ratio", 0)
    postprocess_ratio = stats.get("postprocess_ratio", 0)
    frame_time_std = stats.get("frame_time_std_ms", 0)
    avg_frame_time = stats.get("avg_inference_time_ms", 0)
    
    # 1. 帧率评估
    if target_fps and fps < target_fps:
        analysis["bottlenecks"].append("fps_below_target")
        analysis["optimization_suggestions"].append(
            f"帧率 ({fps:.1f} FPS) 低于目标 ({target_fps} FPS)，建议优化推理流程"
        )
        analysis["overall_rating"] = "needs_improvement"
    
    # 2. 预处理瓶颈
    if preprocess_ratio > 0.3:
        analysis["bottlenecks"].append("preprocess_heavy")
        analysis["optimization_suggestions"].append(
            f"预处理占比过高 ({preprocess_ratio:.1%})，建议："
            "\n  - 使用 SIMD/Neon 加速图像处理"
            "\n  - 实现预处理流水线"
            "\n  - 考虑硬件加速（如 OpenCV 的 UMat）"
        )
    
    # 3. 后处理瓶颈
    if postprocess_ratio > 0.2:
        analysis["bottlenecks"].append("postprocess_heavy")
        analysis["optimization_suggestions"].append(
            f"后处理占比过高 ({postprocess_ratio:.1%})，建议："
            "\n  - 优化 NMS 算法"
            "\n  - 使用多线程后处理"
            "\n  - 批量处理结果"
        )
    
    # 4. 帧时间稳定性
    if frame_time_std > avg_frame_time * 0.3:
        analysis["bottlenecks"].append("unstable_frame_time")
        analysis["optimization_suggestions"].append(
            f"帧时间波动较大 (标准差: {frame_time_std:.2f}ms)，建议："
            "\n  - 检查内存分配模式"
            "\n  - 避免动态内存分配"
            "\n  - 使用内存池"
        )
    
    # 5. 推理时间过长
    if avg_frame_time > 100:  # 超过 100ms
        analysis["bottlenecks"].append("slow_inference")
        analysis["optimization_suggestions"].append(
            f"平均推理时间较长 ({avg_frame_time:.2f}ms)，建议："
            "\n  - 使用 TensorRT/ONNX Runtime 优化"
            "\n  - 启用模型量化（INT8/FP16）"
            "\n  - 优化模型结构（剪枝、蒸馏）"
        )
    
    # 6. 如果没有明显问题
    if not analysis["bottlenecks"]:
        analysis["optimization_suggestions"].append(
            "性能表现良好，建议持续监控以建立性能基线"
        )
    
    return analysis


def print_performance_report(stats: dict):
    """打印详细的性能报告"""
    print("\n" + "=" * 60)
    print("视觉推理性能报告")
    print("=" * 60)
    
    # 基本信息
    print(f"\n📊 基本信息:")
    print(f"  模型复杂度: {stats.get('model_complexity', 'N/A')}")
    print(f"  图像尺寸: {stats.get('image_size', 'N/A')}")
    print(f"  批处理大小: {stats.get('batch_size', 'N/A')}")
    
    # 性能指标
    print(f"\n⚡ 性能指标:")
    print(f"  总帧数: {stats.get('total_frames', 0)}")
    print(f"  总时长: {stats.get('total_time_sec', 0):.2f}秒")
    print(f"  平均帧率: {stats.get('fps', 0):.2f} FPS")
    print(f"  平均推理时间: {stats.get('avg_inference_time_ms', 0):.2f}ms")
    
    # 帧时间分析
    print(f"\n📈 帧时间分析:")
    print(f"  最小帧时间: {stats.get('min_frame_time_ms', 0):.2f}ms")
    print(f"  最大帧时间: {stats.get('max_frame_time_ms', 0):.2f}ms")
    print(f"  P95 帧时间: {stats.get('p95_frame_time_ms', 0):.2f}ms")
    print(f"  帧时间标准差: {stats.get('frame_time_std_ms', 0):.2f}ms")
    
    # 时间分布
    print(f"\n⏱️ 时间分布:")
    print(f"  预处理占比: {stats.get('preprocess_ratio', 0):.1%}")
    print(f"  后处理占比: {stats.get('postprocess_ratio', 0):.1%}")
    
    # 性能分析
    analysis = stats.get("performance_analysis", {})
    print(f"\n🔍 性能分析:")
    print(f"  总体评级: {analysis.get('overall_rating', 'N/A')}")
    
    bottlenecks = analysis.get("bottlenecks", [])
    if bottlenecks:
        print(f"  识别到的瓶颈: {', '.join(bottlenecks)}")
    
    suggestions = analysis.get("optimization_suggestions", [])
    if suggestions:
        print(f"\n💡 优化建议:")
        for i, suggestion in enumerate(suggestions, 1):
            print(f"  {i}. {suggestion}")
    
    print("\n" + "=" * 60)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="视觉推理任务监控示例",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 基本运行
  python examples/inference_monitoring_demo.py --duration 60
  
  # 指定模型复杂度和目标帧率
  python examples/inference_monitoring_demo.py --duration 120 --complexity heavy --target-fps 30
  
  # 与 ai-edge-monitor 配合使用
  # 终端1: ai-edge-monitor run --duration 120 --out reports/inference_optimization
  # 终端2: python examples/inference_monitoring_demo.py --duration 120
        """
    )
    
    parser.add_argument(
        "--duration", 
        type=int, 
        default=60,
        help="运行时长（秒），默认 60"
    )
    parser.add_argument(
        "--image-width", 
        type=int, 
        default=640,
        help="图像宽度，默认 640"
    )
    parser.add_argument(
        "--image-height", 
        type=int, 
        default=480,
        help="图像高度，默认 480"
    )
    parser.add_argument(
        "--batch-size", 
        type=int, 
        default=1,
        help="批处理大小，默认 1"
    )
    parser.add_argument(
        "--complexity", 
        choices=["light", "medium", "heavy"],
        default="medium",
        help="模型复杂度，默认 medium"
    )
    parser.add_argument(
        "--target-fps", 
        type=float, 
        default=None,
        help="目标帧率，用于性能评估"
    )
    parser.add_argument(
        "--progress-interval", 
        type=int, 
        default=5,
        help="进度打印间隔（秒），默认 5"
    )
    
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    
    # 运行推理监控演示
    stats = run_inference_monitoring_demo(
        duration_sec=args.duration,
        image_size=(args.image_width, args.image_height),
        batch_size=args.batch_size,
        model_complexity=args.complexity,
        target_fps=args.target_fps,
        progress_interval_sec=args.progress_interval,
    )
    
    # 打印性能报告
    print_performance_report(stats)
    
    # 返回性能评级对应的退出码
    analysis = stats.get("performance_analysis", {})
    if analysis.get("overall_rating") == "needs_improvement":
        return 1  # 性能未达标
    return 0  # 性能良好


if __name__ == "__main__":
    raise SystemExit(main())