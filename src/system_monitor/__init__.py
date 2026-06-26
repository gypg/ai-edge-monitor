"""系统资源监控模块

扩展监控指标，添加以下功能：
1. 网络I/O监控：网络流量、连接数、错误率
2. 磁盘I/O监控：磁盘读写速度、IOPS、使用率
3. 进程监控：进程数、线程数、文件描述符
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# 尝试导入 psutil
try:
    import psutil
    _PSUTIL_OK = True
except ImportError:
    psutil = None
    _PSUTIL_OK = False


@dataclass
class NetworkIO:
    """网络I/O指标"""
    bytes_sent: int = 0
    bytes_recv: int = 0
    packets_sent: int = 0
    packets_recv: int = 0
    errin: int = 0
    errout: int = 0
    dropin: int = 0
    dropout: int = 0
    connections: int = 0
    timestamp_ms: int = 0


@dataclass
class DiskIO:
    """磁盘I/O指标"""
    read_bytes: int = 0
    write_bytes: int = 0
    read_count: int = 0
    write_count: int = 0
    read_time_ms: int = 0
    write_time_ms: int = 0
    disk_usage_percent: float = 0.0
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_free_gb: float = 0.0
    timestamp_ms: int = 0


@dataclass
class ProcessInfo:
    """进程信息"""
    pid: int = 0
    name: str = ""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_mb: float = 0.0
    num_threads: int = 0
    num_fds: int = 0
    status: str = ""
    timestamp_ms: int = 0


class SystemMonitor:
    """系统资源监控器"""
    
    def __init__(self, collect_interval_ms: int = 1000):
        self.collect_interval_ms = collect_interval_ms
        self._enabled = _PSUTIL_OK
        self._prev_net_io: Optional[NetworkIO] = None
        self._prev_disk_io: Optional[DiskIO] = None
        self._prev_time: Optional[float] = None
        
        if not self._enabled:
            print("Warning: psutil not available, system monitoring disabled")
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    def collect_network_io(self) -> Optional[NetworkIO]:
        """收集网络I/O指标"""
        if not self._enabled:
            return None
        
        try:
            # 获取网络I/O统计
            net_io = psutil.net_io_counters()
            
            # 获取连接数
            connections = len(psutil.net_connections(kind='inet'))
            
            current_time = int(time.time() * 1000)
            
            return NetworkIO(
                bytes_sent=net_io.bytes_sent,
                bytes_recv=net_io.bytes_recv,
                packets_sent=net_io.packets_sent,
                packets_recv=net_io.packets_recv,
                errin=net_io.errin,
                errout=net_io.errout,
                dropin=net_io.dropin,
                dropout=net_io.dropout,
                connections=connections,
                timestamp_ms=current_time,
            )
        except Exception as e:
            print(f"Error collecting network I/O: {e}")
            return None
    
    def collect_network_io_rates(self) -> Optional[Dict[str, float]]:
        """收集网络I/O速率（字节/秒）"""
        current_io = self.collect_network_io()
        if current_io is None:
            return None
        
        current_time = time.time()
        
        if self._prev_net_io is not None and self._prev_time is not None:
            time_delta = current_time - self._prev_time
            if time_delta > 0:
                return {
                    "net_send_rate_bps": (current_io.bytes_sent - self._prev_net_io.bytes_sent) / time_delta,
                    "net_recv_rate_bps": (current_io.bytes_recv - self._prev_net_io.bytes_recv) / time_delta,
                    "net_packet_send_rate": (current_io.packets_sent - self._prev_net_io.packets_sent) / time_delta,
                    "net_packet_recv_rate": (current_io.packets_recv - self._prev_net_io.packets_recv) / time_delta,
                }
        
        self._prev_net_io = current_io
        self._prev_time = current_time
        return {
            "net_send_rate_bps": 0.0,
            "net_recv_rate_bps": 0.0,
            "net_packet_send_rate": 0.0,
            "net_packet_recv_rate": 0.0,
        }
    
    def collect_disk_io(self) -> Optional[DiskIO]:
        """收集磁盘I/O指标"""
        if not self._enabled:
            return None
        
        try:
            # 获取磁盘I/O统计
            disk_io = psutil.disk_io_counters()
            
            # 获取磁盘使用情况
            disk_usage = psutil.disk_usage('/')
            
            current_time = int(time.time() * 1000)
            
            return DiskIO(
                read_bytes=disk_io.read_bytes,
                write_bytes=disk_io.write_bytes,
                read_count=disk_io.read_count,
                write_count=disk_io.write_count,
                read_time_ms=disk_io.read_time,
                write_time_ms=disk_io.write_time,
                disk_usage_percent=disk_usage.percent,
                disk_total_gb=disk_usage.total / (1024**3),
                disk_used_gb=disk_usage.used / (1024**3),
                disk_free_gb=disk_usage.free / (1024**3),
                timestamp_ms=current_time,
            )
        except Exception as e:
            print(f"Error collecting disk I/O: {e}")
            return None
    
    def collect_disk_io_rates(self) -> Optional[Dict[str, float]]:
        """收集磁盘I/O速率（字节/秒和IOPS）"""
        current_io = self.collect_disk_io()
        if current_io is None:
            return None
        
        current_time = time.time()
        
        if self._prev_disk_io is not None and self._prev_time is not None:
            time_delta = current_time - self._prev_time
            if time_delta > 0:
                return {
                    "disk_read_rate_bps": (current_io.read_bytes - self._prev_disk_io.read_bytes) / time_delta,
                    "disk_write_rate_bps": (current_io.write_bytes - self._prev_disk_io.write_bytes) / time_delta,
                    "disk_read_iops": (current_io.read_count - self._prev_disk_io.read_count) / time_delta,
                    "disk_write_iops": (current_io.write_count - self._prev_disk_io.write_count) / time_delta,
                    "disk_usage_percent": current_io.disk_usage_percent,
                }
        
        self._prev_disk_io = current_io
        return {
            "disk_read_rate_bps": 0.0,
            "disk_write_rate_bps": 0.0,
            "disk_read_iops": 0.0,
            "disk_write_iops": 0.0,
            "disk_usage_percent": current_io.disk_usage_percent,
        }
    
    def collect_process_info(self, pid: Optional[int] = None) -> Optional[ProcessInfo]:
        """收集进程信息"""
        if not self._enabled:
            return None
        
        try:
            if pid is None:
                pid = os.getpid()
            
            process = psutil.Process(pid)
            
            with process.oneshot():
                return ProcessInfo(
                    pid=pid,
                    name=process.name(),
                    cpu_percent=process.cpu_percent(),
                    memory_percent=process.memory_percent(),
                    memory_mb=process.memory_info().rss / (1024**2),
                    num_threads=process.num_threads(),
                    num_fds=process.num_fds() if hasattr(process, 'num_fds') else 0,
                    status=process.status(),
                    timestamp_ms=int(time.time() * 1000),
                )
        except Exception as e:
            print(f"Error collecting process info: {e}")
            return None
    
    def collect_system_summary(self) -> Dict[str, Any]:
        """收集系统摘要信息"""
        summary: Dict[str, Any] = {
            "timestamp_ms": int(time.time() * 1000),
            "enabled": self._enabled,
        }
        
        if not self._enabled:
            return summary
        
        try:
            # CPU 信息
            summary["cpu_count"] = psutil.cpu_count()
            summary["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            summary["cpu_freq_mhz"] = psutil.cpu_freq().current if psutil.cpu_freq() else 0
            
            # 内存信息
            memory = psutil.virtual_memory()
            summary["memory_total_gb"] = memory.total / (1024**3)
            summary["memory_used_gb"] = memory.used / (1024**3)
            summary["memory_percent"] = memory.percent
            
            # 网络信息
            net_io = self.collect_network_io()
            if net_io:
                summary["net_bytes_sent"] = net_io.bytes_sent
                summary["net_bytes_recv"] = net_io.bytes_recv
                summary["net_connections"] = net_io.connections
            
            # 磁盘信息
            disk_io = self.collect_disk_io()
            if disk_io:
                summary["disk_read_bytes"] = disk_io.read_bytes
                summary["disk_write_bytes"] = disk_io.write_bytes
                summary["disk_usage_percent"] = disk_io.disk_usage_percent
            
            # 进程信息
            process = self.collect_process_info()
            if process:
                summary["process_pid"] = process.pid
                summary["process_memory_mb"] = process.memory_mb
                summary["process_threads"] = process.num_threads
            
        except Exception as e:
            summary["error"] = str(e)
        
        return summary
    
    def format_bytes(self, bytes_value: int) -> str:
        """格式化字节数为可读字符串"""
        val = float(bytes_value)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if val < 1024.0:
                return f"{val:.2f} {unit}"
            val /= 1024.0
        return f"{val:.2f} PB"


# 便捷函数
def create_system_monitor(collect_interval_ms: int = 1000) -> SystemMonitor:
    """创建系统监控器实例"""
    return SystemMonitor(collect_interval_ms)


def quick_system_check() -> Dict[str, Any]:
    """快速系统检查"""
    monitor = SystemMonitor()
    return monitor.collect_system_summary()