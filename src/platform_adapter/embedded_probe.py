"""嵌入式设备专用探测器（Jetson / Raspberry Pi）

支持以下设备：
- NVIDIA Jetson 系列（Nano, TX2, Xavier, Orin）
- Raspberry Pi 系列（3B+, 4B, 5）

提供以下能力：
- CPU/内存/温度监控
- GPU 利用率和显存（Jetson）
- 功耗监控（Jetson）
- 专用硬件信息检测
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .probe import PlatformCaps, PlatformProbe, RawMetrics


@dataclass
class EmbeddedDevice:
    """嵌入式设备信息"""
    name: str
    platform: str  # "jetson" or "rpi"
    model: str
    has_gpu: bool
    has_temp_sensor: bool
    has_power_sensor: bool
    capabilities: Dict[str, Any]


class EmbeddedProbe(PlatformProbe):
    """嵌入式设备专用探测器"""
    
    name = "embedded"
    
    # Jetson 设备型号映射
    JETSON_MODELS = {
        "jetson-nano": "Jetson Nano",
        "jetson-tx2": "Jetson TX2",
        "jetson-xavier": "Jetson Xavier",
        "jetson-orin": "Jetson Orin",
    }
    
    # Raspberry Pi 设备型号映射
    RPI_MODELS = {
        "rpi-3b+": "Raspberry Pi 3B+",
        "rpi-4b": "Raspberry Pi 4B",
        "rpi-5": "Raspberry Pi 5",
    }
    
    def __init__(self) -> None:
        self._device: Optional[EmbeddedDevice] = None
        self._prev_cpu: Optional[Tuple[int, int]] = None
        self._detect_device()
    
    def _detect_device(self) -> None:
        """检测嵌入式设备类型"""
        # 检测 Jetson
        if self._is_jetson():
            self._device = self._detect_jetson()
            return
        
        # 检测 Raspberry Pi
        if self._is_rpi():
            self._device = self._detect_rpi()
            return
        
        # 未知设备
        self._device = None
    
    def _is_jetson(self) -> bool:
        """检测是否为 Jetson 设备"""
        # 方法1: 检查 /etc/nv_tegra_release
        if os.path.exists("/etc/nv_tegra_release"):
            return True
        
        # 方法2: 检查 jtop 命令
        try:
            result = subprocess.run(
                ["jtop", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        # 方法3: 检查 nvidia-smi
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and "jetson" in result.stdout.lower():
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        return False
    
    def _is_rpi(self) -> bool:
        """检测是否为 Raspberry Pi 设备"""
        # 方法1: 检查 /proc/cpuinfo
        try:
            with open("/proc/cpuinfo", "r") as f:
                content = f.read().lower()
                if "raspberry pi" in content or "bcm2" in content:
                    return True
        except (OSError, IOError):
            pass
        
        # 方法2: 检查 /sys/firmware/devicetree/base/model
        try:
            with open("/sys/firmware/devicetree/base/model", "r") as f:
                model = f.read().strip().lower()
                if "raspberry pi" in model:
                    return True
        except (OSError, IOError):
            pass
        
        return False
    
    def _detect_jetson(self) -> EmbeddedDevice:
        """检测 Jetson 设备详细信息"""
        model = "jetson-nano"  # 默认
        has_gpu = True
        has_temp_sensor = True
        has_power_sensor = True
        
        # 检测具体型号
        try:
            with open("/etc/nv_tegra_release", "r") as f:
                content = f.read()
                # 提取型号信息
                for line in content.splitlines():
                    if "BOARD" in line:
                        # 例如: BOARD: jetson-nano
                        for key, value in self.JETSON_MODELS.items():
                            if key in line.lower():
                                model = key
                                break
        except (OSError, IOError):
            pass
        
        # 检测 GPU 能力
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                has_gpu = False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            has_gpu = False
        
        # 检测温度传感器
        if not os.path.exists("/sys/class/thermal"):
            has_temp_sensor = False
        
        # 检测功耗传感器
        if not os.path.exists("/sys/class/power_supply"):
            has_power_sensor = False
        
        capabilities = {
            "cuda": has_gpu,
            "tensorrt": has_gpu,
            "tegra": True,
            "jtop": True,
        }
        
        return EmbeddedDevice(
            name=model,
            platform="jetson",
            model=self.JETSON_MODELS.get(model, model),
            has_gpu=has_gpu,
            has_temp_sensor=has_temp_sensor,
            has_power_sensor=has_power_sensor,
            capabilities=capabilities,
        )
    
    def _detect_rpi(self) -> EmbeddedDevice:
        """检测 Raspberry Pi 设备详细信息"""
        model = "rpi-4b"  # 默认
        has_gpu = False
        has_temp_sensor = True
        has_power_sensor = False
        
        # 检测具体型号
        try:
            with open("/proc/cpuinfo", "r") as f:
                content = f.read()
                # 提取型号信息
                for line in content.splitlines():
                    if "model name" in line.lower():
                        # 例如: model name : ARMv7 Processor rev 4 (v7l)
                        for key, value in self.RPI_MODELS.items():
                            if key in line.lower():
                                model = key
                                break
        except (OSError, IOError):
            pass
        
        # 检测温度传感器
        if not os.path.exists("/sys/class/thermal"):
            has_temp_sensor = False
        
        # Raspberry Pi 4B+ 支持 GPU 监控
        if model in ["rpi-4b", "rpi-5"]:
            has_gpu = True
        
        capabilities = {
            "vcgencmd": True,
            "gpio": True,
            "camera": True,
        }
        
        return EmbeddedDevice(
            name=model,
            platform="rpi",
            model=self.RPI_MODELS.get(model, model),
            has_gpu=has_gpu,
            has_temp_sensor=has_temp_sensor,
            has_power_sensor=has_power_sensor,
            capabilities=capabilities,
        )
    
    def is_available(self) -> bool:
        """检查是否为支持的嵌入式设备"""
        return self._device is not None
    
    def detect_caps(self) -> PlatformCaps:
        """检测设备能力"""
        if self._device is None:
            return PlatformCaps(
                platform_name="unknown-embedded",
                notes={"error": "unsupported embedded device"},
            )
        
        return PlatformCaps(
            has_cpu=True,
            has_mem=True,
            has_gpu=self._device.has_gpu,
            has_temp_sensor=self._device.has_temp_sensor,
            has_power_sensor=self._device.has_power_sensor,
            platform_name=f"{self._device.platform}-{self._device.name}",
            notes={
                "device_model": self._device.model,
                "platform": self._device.platform,
                "capabilities": str(self._device.capabilities),
            },
        )
    
    def read_metrics(self) -> RawMetrics:
        """读取设备指标"""
        started = time.perf_counter()
        ts_ms = int(time.time() * 1000)
        
        if self._device is None:
            return RawMetrics(
                ts_ms=ts_ms,
                cpu_percent=0.0,
                mem_used_mb=0.0,
                mem_total_mb=0.0,
                gpu_percent=None,
                gpu_mem_used_mb=None,
                temperature_c=None,
                probe_name=self.name,
                status="not_supported",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error_message="unsupported embedded device",
            )
        
        # 读取 CPU
        cpu_pct = self._read_cpu()
        
        # 读取内存
        mem_used, mem_total = self._read_memory()
        
        # 读取温度
        temp_c = self._read_temperature()
        
        # 读取 GPU（如果支持）
        gpu_pct, gpu_mem = self._read_gpu() if self._device.has_gpu else (None, None)
        
        latency_ms = (time.perf_counter() - started) * 1000.0
        
        return RawMetrics(
            ts_ms=ts_ms,
            cpu_percent=cpu_pct,
            mem_used_mb=mem_used,
            mem_total_mb=mem_total,
            gpu_percent=gpu_pct,
            gpu_mem_used_mb=gpu_mem,
            temperature_c=temp_c,
            probe_name=self.name,
            status="ok",
            latency_ms=latency_ms,
        )
    
    def _read_cpu(self) -> float:
        """读取 CPU 使用率"""
        try:
            with open("/proc/stat", "r") as f:
                line = f.readline()
                parts = line.split()
                if not parts or parts[0] != "cpu":
                    return 0.0
                
                nums = [int(x) for x in parts[1:]]
                idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
                total = sum(nums)
                
                if self._prev_cpu is not None:
                    d_idle = idle - self._prev_cpu[0]
                    d_total = total - self._prev_cpu[1]
                    if d_total > 0:
                        cpu_pct = max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0))
                        self._prev_cpu = (idle, total)
                        return cpu_pct
                
                self._prev_cpu = (idle, total)
                return 0.0
        except (OSError, IOError):
            return 0.0
    
    def _read_memory(self) -> Tuple[float, float]:
        """读取内存使用情况"""
        try:
            with open("/proc/meminfo", "r") as f:
                total_kb = avail_kb = None
                for line in f:
                    if line.startswith("MemTotal:"):
                        total_kb = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        avail_kb = int(line.split()[1])
                    if total_kb is not None and avail_kb is not None:
                        break
                
                if total_kb is None:
                    return 0.0, 0.0
                
                used_mb = max(0.0, (total_kb - (avail_kb or 0)) / 1024.0)
                total_mb = total_kb / 1024.0
                return used_mb, total_mb
        except (OSError, IOError):
            return 0.0, 0.0
    
    def _read_temperature(self) -> Optional[float]:
        """读取温度"""
        try:
            # 查找温度传感器
            thermal_dir = "/sys/class/thermal"
            if not os.path.isdir(thermal_dir):
                return None
            
            for entry in sorted(os.listdir(thermal_dir)):
                temp_path = os.path.join(thermal_dir, entry, "temp")
                if os.path.isfile(temp_path):
                    with open(temp_path, "r") as f:
                        temp = int(f.read().strip())
                        return temp / 1000.0
        except (OSError, IOError, ValueError):
            pass
        
        return None
    
    def _read_gpu(self) -> Tuple[Optional[float], Optional[float]]:
        """读取 GPU 使用率和显存"""
        if self._device is None or not self._device.has_gpu:
            return None, None
        
        try:
            # Jetson 使用 nvidia-smi
            if self._device.platform == "jetson":
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    if lines:
                        parts = lines[0].split(",")
                        if len(parts) >= 2:
                            gpu_pct = float(parts[0].strip())
                            gpu_mem_mb = float(parts[1].strip())
                            return gpu_pct, gpu_mem_mb
            
            # Raspberry Pi 使用 vcgencmd
            elif self._device.platform == "rpi":
                # 获取 GPU 内存
                result = subprocess.run(
                    ["vcgencmd", "get_mem", "gpu"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    # 解析输出: gpu=76M
                    match = re.search(r"gpu=(\d+)M", result.stdout)
                    if match:
                        gpu_mem_mb = float(match.group(1))
                        return None, gpu_mem_mb
        
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            pass
        
        return None, None
    
    def get_device_info(self) -> Dict[str, Any]:
        """获取设备详细信息"""
        if self._device is None:
            return {"error": "unsupported embedded device"}
        
        return {
            "name": self._device.name,
            "platform": self._device.platform,
            "model": self._device.model,
            "has_gpu": self._device.has_gpu,
            "has_temp_sensor": self._device.has_temp_sensor,
            "has_power_sensor": self._device.has_power_sensor,
            "capabilities": self._device.capabilities,
        }