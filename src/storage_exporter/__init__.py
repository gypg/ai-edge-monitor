from __future__ import annotations

import csv
import gzip
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

OutputPath = Union[str, Path]
MetricRow = Mapping[str, Any]

# 默认配置
DEFAULT_MAX_FILE_SIZE_MB = 100  # 单个文件最大 100MB
DEFAULT_MAX_TOTAL_SIZE_MB = 1000  # 总磁盘配额 1GB
DEFAULT_MAX_FILES = 10  # 最多保留 10 个轮转文件
DEFAULT_ROTATE_CHECK_INTERVAL = 60  # 每 60 秒检查一次是否需要轮转


class StorageError(OSError):
    """存储相关错误"""
    pass


class JsonlExporter:
    """JSONL 格式导出器，支持文件轮转和磁盘配额管理"""
    
    def __init__(
        self,
        output_dir: OutputPath,
        max_file_size_mb: float = DEFAULT_MAX_FILE_SIZE_MB,
        max_total_size_mb: float = DEFAULT_MAX_TOTAL_SIZE_MB,
        max_files: int = DEFAULT_MAX_FILES,
        enable_compression: bool = False,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.max_file_size_bytes = int(max_file_size_mb * 1024 * 1024)
        self.max_total_size_bytes = int(max_total_size_mb * 1024 * 1024)
        self.max_files = max_files
        self.enable_compression = enable_compression
        self._current_file_size = 0
        self._last_rotate_check = 0.0

    def write_metrics(self, metrics: Iterable[MetricRow]) -> Path:
        rows = list(metrics)
        if not rows:
            return self.output_dir / "metrics.jsonl"
        
        _ensure_output_dir(self.output_dir)
        
        # 检查是否需要轮转
        self._check_rotation()
        
        # 写入数据
        path = self._get_current_file_path()
        with path.open("a", encoding="utf-8") as fh:
            for row in rows:
                line = json.dumps(dict(row), ensure_ascii=False, sort_keys=True)
                fh.write(line + "\n")
                self._current_file_size += len(line.encode("utf-8")) + 1
        
        # 检查磁盘配额
        self._check_disk_quota()
        
        return path

    def _get_current_file_path(self) -> Path:
        """获取当前写入的文件路径"""
        return self.output_dir / "metrics.jsonl"

    def _check_rotation(self) -> None:
        """检查是否需要文件轮转"""
        current_path = self._get_current_file_path()
        if not current_path.exists():
            self._current_file_size = 0
            return
        
        current_size = current_path.stat().st_size
        if current_size >= self.max_file_size_bytes:
            self._rotate_file(current_path)

    def _rotate_file(self, file_path: Path) -> None:
        """执行文件轮转"""
        # 生成轮转文件名
        timestamp = int(time.time())
        rotate_name = f"metrics_{timestamp}.jsonl"
        if self.enable_compression:
            rotate_name += ".gz"
        
        rotate_path = self.output_dir / rotate_name
        
        # 如果目标文件已存在，添加序号
        counter = 1
        while rotate_path.exists():
            rotate_name = f"metrics_{timestamp}_{counter}.jsonl"
            if self.enable_compression:
                rotate_name += ".gz"
            rotate_path = self.output_dir / rotate_name
            counter += 1
        
        # 压缩或移动文件
        if self.enable_compression:
            with open(file_path, "rb") as f_in:
                with gzip.open(rotate_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            file_path.unlink()
        else:
            file_path.rename(rotate_path)
        
        # 重置当前文件大小
        self._current_file_size = 0
        
        # 清理旧文件
        self._cleanup_old_files()

    def _check_disk_quota(self) -> None:
        """检查磁盘配额"""
        total_size = self._get_total_size()
        if total_size > self.max_total_size_bytes:
            self._cleanup_old_files()

    def _get_total_size(self) -> int:
        """获取目录总大小"""
        total = 0
        for file_path in self.output_dir.glob("metrics*.jsonl*"):
            if file_path.is_file():
                total += file_path.stat().st_size
        return total

    def _cleanup_old_files(self) -> None:
        """清理旧文件"""
        # 获取所有轮转文件
        rotated_files = []
        for pattern in ["metrics_*.jsonl", "metrics_*.jsonl.gz"]:
            rotated_files.extend(self.output_dir.glob(pattern))
        
        # 按修改时间排序
        rotated_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        # 删除超出数量限制的文件
        while len(rotated_files) > self.max_files:
            old_file = rotated_files.pop()
            old_file.unlink()
        
        # 如果仍然超过配额，删除最旧的文件
        total_size = self._get_total_size()
        while total_size > self.max_total_size_bytes and rotated_files:
            old_file = rotated_files.pop()
            total_size -= old_file.stat().st_size
            old_file.unlink()

    def get_storage_stats(self) -> Dict[str, Any]:
        """获取存储统计信息"""
        total_size = self._get_total_size()
        file_count = len(list(self.output_dir.glob("metrics*.jsonl*")))
        
        return {
            "total_size_mb": total_size / (1024 * 1024),
            "file_count": file_count,
            "max_file_size_mb": self.max_file_size_bytes / (1024 * 1024),
            "max_total_size_mb": self.max_total_size_bytes / (1024 * 1024),
            "max_files": self.max_files,
            "compression_enabled": self.enable_compression,
        }


class CsvExporter:
    """CSV 格式导出器，支持文件轮转"""
    
    def __init__(
        self,
        output_dir: OutputPath,
        max_file_size_mb: float = DEFAULT_MAX_FILE_SIZE_MB,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.max_file_size_bytes = int(max_file_size_mb * 1024 * 1024)
        self._current_file_size = 0

    def write_metrics(self, metrics: Iterable[MetricRow]) -> Path:
        rows = [dict(row) for row in metrics]
        if not rows:
            return self.output_dir / "metrics.csv"
        
        _ensure_output_dir(self.output_dir)
        
        # 检查是否需要轮转
        self._check_rotation()
        
        # 写入数据
        path = self._get_current_file_path()
        fieldnames = _fieldnames(rows)
        
        # 如果文件不存在，写入表头
        write_header = not path.exists()
        
        with path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerows(rows)
            self._current_file_size = path.stat().st_size
        
        return path

    def _get_current_file_path(self) -> Path:
        """获取当前写入的文件路径"""
        return self.output_dir / "metrics.csv"

    def _check_rotation(self) -> None:
        """检查是否需要文件轮转"""
        current_path = self._get_current_file_path()
        if not current_path.exists():
            self._current_file_size = 0
            return
        
        current_size = current_path.stat().st_size
        if current_size >= self.max_file_size_bytes:
            self._rotate_file(current_path)

    def _rotate_file(self, file_path: Path) -> None:
        """执行文件轮转"""
        timestamp = int(time.time())
        rotate_name = f"metrics_{timestamp}.csv"
        rotate_path = self.output_dir / rotate_name
        
        # 如果目标文件已存在，添加序号
        counter = 1
        while rotate_path.exists():
            rotate_name = f"metrics_{timestamp}_{counter}.csv"
            rotate_path = self.output_dir / rotate_name
            counter += 1
        
        file_path.rename(rotate_path)
        self._current_file_size = 0


class SummaryExporter:
    """摘要导出器"""
    
    def __init__(self, output_dir: OutputPath) -> None:
        self.output_dir = Path(output_dir)

    def write_summary(self, summary: Mapping[str, Any]) -> Path:
        path = self.output_dir / "summary.json"
        if not summary:
            return path
        _ensure_output_dir(self.output_dir)
        path.write_text(json.dumps(dict(summary), indent=2, ensure_ascii=False), encoding="utf-8")
        return path


class StorageManager:
    """存储管理器，统一管理所有导出器"""
    
    def __init__(
        self,
        output_dir: OutputPath,
        max_file_size_mb: float = DEFAULT_MAX_FILE_SIZE_MB,
        max_total_size_mb: float = DEFAULT_MAX_TOTAL_SIZE_MB,
        max_files: int = DEFAULT_MAX_FILES,
        enable_compression: bool = False,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.jsonl_exporter = JsonlExporter(
            output_dir=output_dir,
            max_file_size_mb=max_file_size_mb,
            max_total_size_mb=max_total_size_mb,
            max_files=max_files,
            enable_compression=enable_compression,
        )
        self.csv_exporter = CsvExporter(
            output_dir=output_dir,
            max_file_size_mb=max_file_size_mb,
        )
        self.summary_exporter = SummaryExporter(output_dir=output_dir)

    def write_all(
        self,
        metrics: Iterable[MetricRow],
        summary: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Path]:
        """写入所有格式的数据"""
        results = {}
        
        # 写入 JSONL
        results["jsonl"] = self.jsonl_exporter.write_metrics(metrics)
        
        # 写入 CSV
        results["csv"] = self.csv_exporter.write_metrics(metrics)
        
        # 写入摘要
        if summary:
            results["summary"] = self.summary_exporter.write_summary(summary)
        
        return results

    def get_storage_stats(self) -> Dict[str, Any]:
        """获取存储统计信息"""
        return self.jsonl_exporter.get_storage_stats()

    def cleanup(self) -> None:
        """清理旧文件"""
        self.jsonl_exporter._cleanup_old_files()


def _ensure_output_dir(output_dir: Path) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise StorageError(f"output path is not a directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)


def _fieldnames(rows: Sequence[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    seen = set()
    for row in rows:
        for name in row:
            if name not in seen:
                names.append(name)
                seen.add(name)
    return names
