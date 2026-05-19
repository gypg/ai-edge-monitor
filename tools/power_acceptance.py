"""power_acceptance.py

用于 `power_monitor` 模块的自动化验收测试脚本，支持真实数据源与 DummySource。

功能摘要：
- 默认执行 12 分钟采样（含 2 分钟预热 + 10 分钟评估）。
- 自动计算关键指标并输出 PASS/FAIL。
- 在无真实功耗传感器环境中可使用 DummySource 立即运行。

依赖包：
- Python >= 3.9
- psutil

安装示例：
    pip install psutil

运行示例：
1) 快速自测（DummySource，缩短时长）：
    python tools/power_acceptance.py --source dummy \
        --duration-sec 90 --warmup-sec 10 --interval-ms 1000

2) 标准验收（DummySource，12分钟）：
    python tools/power_acceptance.py --source dummy \
        --duration-sec 720 --warmup-sec 120 --interval-ms 1000

3) sysfs 真实采集（若设备支持 /sys/class/power_supply）：
    python tools/power_acceptance.py --source sysfs --device rpi4b --interval-ms 1000

输出：
- 控制台打印 PASS/FAIL 与关键指标。
- 可选写入 JSON 报告：
    python tools/power_acceptance.py --source dummy --report-json ./acceptance_result.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Optional

try:
    import psutil  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    psutil = None

Quality = Literal["raw", "derived", "estimated", "unavailable"]
ReadStatus = Literal["ok", "timeout", "io_error", "parse_error", "not_supported"]


@dataclass(slots=True)
class PowerConfig:
    sample_interval_ms: int = 1000
    read_timeout_ms: int = 50


@dataclass(slots=True)
class PowerReading:
    ts_ms: int
    power_watt: Optional[float]
    voltage_v: Optional[float]
    current_a: Optional[float]
    source_name: str
    quality: Quality
    status: ReadStatus
    latency_ms: float
    error_message: Optional[str] = None


@dataclass(slots=True)
class PowerSample:
    reading: PowerReading
    seq: int


class DummySource:
    name = "dummy"

    def __init__(self, base_watt: float = 8.0, jitter_watt: float = 1.5, fail_rate: float = 0.0):
        self.base_watt = base_watt
        self.jitter_watt = jitter_watt
        self.fail_rate = fail_rate

    def is_available(self) -> bool:
        return True

    def read_once(self, timeout_ms: int) -> PowerReading:
        started = time.perf_counter()
        if random.random() < self.fail_rate:
            latency = (time.perf_counter() - started) * 1000.0
            return PowerReading(
                ts_ms=int(time.time() * 1000),
                power_watt=None,
                voltage_v=None,
                current_a=None,
                source_name=self.name,
                quality="unavailable",
                status="timeout",
                latency_ms=latency,
                error_message="dummy injected timeout",
            )

        power = max(0.1, self.base_watt + random.uniform(-self.jitter_watt, self.jitter_watt))
        voltage = 5.0
        current = power / voltage
        latency = (time.perf_counter() - started) * 1000.0
        return PowerReading(
            ts_ms=int(time.time() * 1000),
            power_watt=power,
            voltage_v=voltage,
            current_a=current,
            source_name=self.name,
            quality="raw",
            status="ok",
            latency_ms=latency,
        )

    def close(self) -> None:
        return None


class SysfsPowerSource:
    name = "sysfs"

    def __init__(self, base_path: str = "/sys/class/power_supply"):
        self.base_path = Path(base_path)
        self.power_now_path: Optional[Path] = None
        self.current_now_path: Optional[Path] = None
        self.voltage_now_path: Optional[Path] = None
        self._discover()

    def _discover(self) -> None:
        if not self.base_path.exists():
            return
        for node in self.base_path.iterdir():
            power_now = node / "power_now"
            current_now = node / "current_now"
            voltage_now = node / "voltage_now"
            if power_now.exists() and power_now.is_file():
                self.power_now_path = power_now
                return
            if (
                current_now.exists()
                and voltage_now.exists()
                and current_now.is_file()
                and voltage_now.is_file()
            ):
                self.current_now_path = current_now
                self.voltage_now_path = voltage_now
                return

    def is_available(self) -> bool:
        return self.power_now_path is not None or (
            self.current_now_path is not None and self.voltage_now_path is not None
        )

    def _read_int(self, path: Path) -> int:
        return int(path.read_text(encoding="utf-8").strip())

    def read_once(self, timeout_ms: int) -> PowerReading:
        started = time.perf_counter()
        try:
            if self.power_now_path is not None:
                raw_uw = self._read_int(self.power_now_path)
                power_watt = raw_uw / 1_000_000.0
                latency = (time.perf_counter() - started) * 1000.0
                return PowerReading(
                    ts_ms=int(time.time() * 1000),
                    power_watt=power_watt,
                    voltage_v=None,
                    current_a=None,
                    source_name=self.name,
                    quality="raw",
                    status="ok",
                    latency_ms=latency,
                )

            if self.current_now_path is not None and self.voltage_now_path is not None:
                raw_ua = self._read_int(self.current_now_path)
                raw_uv = self._read_int(self.voltage_now_path)
                current_a = raw_ua / 1_000_000.0
                voltage_v = raw_uv / 1_000_000.0
                power_watt = current_a * voltage_v
                latency = (time.perf_counter() - started) * 1000.0
                return PowerReading(
                    ts_ms=int(time.time() * 1000),
                    power_watt=power_watt,
                    voltage_v=voltage_v,
                    current_a=current_a,
                    source_name=self.name,
                    quality="derived",
                    status="ok",
                    latency_ms=latency,
                )

            latency = (time.perf_counter() - started) * 1000.0
            return PowerReading(
                ts_ms=int(time.time() * 1000),
                power_watt=None,
                voltage_v=None,
                current_a=None,
                source_name=self.name,
                quality="unavailable",
                status="not_supported",
                latency_ms=latency,
                error_message="no readable sysfs power node",
            )
        except Exception as exc:
            latency = (time.perf_counter() - started) * 1000.0
            return PowerReading(
                ts_ms=int(time.time() * 1000),
                power_watt=None,
                voltage_v=None,
                current_a=None,
                source_name=self.name,
                quality="unavailable",
                status="io_error",
                latency_ms=latency,
                error_message=str(exc),
            )

    def close(self) -> None:
        return None


def percentile(values: list[float], q: float) -> Optional[float]:
    if not values:
        return None
    if q <= 0:
        return min(values)
    if q >= 100:
        return max(values)
    ordered = sorted(values)
    pos = (len(ordered) - 1) * (q / 100.0)
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def evaluate_thresholds(
    *,
    device_type: str,
    selected_source: str,
    interval_ms: int,
    expected_eval_samples: int,
    latency_p95: Optional[float],
    latency_p99: Optional[float],
    jitter_p95: Optional[float],
    monitor_cpu_pct_p95: Optional[float],
    fail_rate: float,
    rss_delta_mb: float,
    sample_count: int,
    quality_bad_count: int,
) -> dict:
    reasons: list[str] = []

    min_samples = max(1, int(expected_eval_samples * 0.98))
    if sample_count < min_samples:
        reasons.append(f"有效样本不足（低于评估窗口预期的98%，期望>={min_samples}）")

    if rss_delta_mb > 5.0:
        reasons.append("常驻内存增量超过5MB")

    jitter_limit_ms = interval_ms * 0.1
    if jitter_p95 is None or jitter_p95 > jitter_limit_ms:
        reasons.append(f"采样抖动P95超阈值（>{jitter_limit_ms:.1f}ms）")

    if monitor_cpu_pct_p95 is None or monitor_cpu_pct_p95 >= 2.0:
        reasons.append("监控进程CPU占比P95超阈值（>=2%）")

    if quality_bad_count > 0:
        reasons.append("存在quality与功耗值不一致样本")

    # 根据源类型应用延迟阈值
    if latency_p95 is None:
        reasons.append("缺少有效延迟数据")
    else:
        if selected_source == "sysfs":
            if latency_p95 >= 5.0:
                reasons.append("sysfs链路 latency_p95 >= 5ms")
            if latency_p99 is not None and latency_p99 >= 8.0:
                reasons.append("sysfs链路 latency_p99 >= 8ms")
        elif selected_source == "dummy":
            if latency_p95 >= 5.0:
                reasons.append("dummy链路 latency_p95 >= 5ms")
        else:
            if latency_p95 >= 12.0:
                reasons.append("fallback链路 latency_p95 >= 12ms")

    # 失败率阈值：无真实传感器允许放宽
    relaxed_mode = selected_source == "dummy"
    fail_threshold = 0.05 if relaxed_mode else 0.01
    if fail_rate > fail_threshold:
        reasons.append(f"失败率超过阈值（>{fail_threshold:.2%}）")

    return {
        "pass": len(reasons) == 0,
        "reasons": reasons,
        "metrics": {
            "device_type": device_type,
            "selected_source": selected_source,
            "latency_p95_ms": latency_p95,
            "latency_p99_ms": latency_p99,
            "jitter_p95_ms": jitter_p95,
            "monitor_cpu_pct_p95": monitor_cpu_pct_p95,
            "fail_rate": fail_rate,
            "rss_delta_mb": rss_delta_mb,
            "sample_count": sample_count,
        },
    }


def select_source(source_arg: str):
    if source_arg == "dummy":
        return DummySource()
    if source_arg == "sysfs":
        src = SysfsPowerSource()
        if src.is_available():
            return src
        return DummySource()
    raise ValueError(f"unsupported source: {source_arg}")


def run_acceptance(
    *,
    device_type: str,
    source_name: str,
    interval_ms: int,
    duration_sec: int,
    warmup_sec: int,
) -> dict:
    cfg = PowerConfig(sample_interval_ms=interval_ms)
    source = select_source(source_name)
    selected_source = source.name

    proc = psutil.Process() if psutil is not None else None
    rss_baseline = (proc.memory_info().rss / (1024 * 1024)) if proc is not None else 0.0

    latencies: list[float] = []
    jitters: list[float] = []
    cpu_pct_samples: list[float] = []

    fail_count = 0
    quality_bad_count = 0
    eval_samples = 0

    total_loops = max(1, int((duration_sec * 1000) / interval_ms))
    warmup_loops = int((warmup_sec * 1000) / interval_ms)

    if proc is not None:
        proc.cpu_percent(interval=None)

    seq = 0
    next_tick = time.monotonic()
    last_tick = next_tick

    try:
        for i in range(total_loops):
            now = time.monotonic()
            sleep_s = max(0.0, next_tick - now)
            if sleep_s > 0:
                time.sleep(sleep_s)

            tick = time.monotonic()
            jitter_ms = abs((tick - last_tick) * 1000.0 - interval_ms)
            last_tick = tick

            reading = source.read_once(cfg.read_timeout_ms)
            _ = PowerSample(reading=reading, seq=seq)
            seq += 1

            cpu_pct_samples.append(proc.cpu_percent(interval=None) if proc is not None else 0.0)

            if i >= warmup_loops:
                eval_samples += 1
                jitters.append(jitter_ms)
                if reading.status == "ok":
                    latencies.append(reading.latency_ms)
                else:
                    fail_count += 1

                if reading.quality == "raw" and reading.power_watt is None:
                    quality_bad_count += 1

            next_tick += interval_ms / 1000.0
    finally:
        source.close()

    rss_end = (proc.memory_info().rss / (1024 * 1024)) if proc is not None else 0.0
    rss_delta_mb = rss_end - rss_baseline

    fail_rate = (fail_count / eval_samples) if eval_samples else 1.0

    eval_expected = max(1, total_loops - warmup_loops)

    result = evaluate_thresholds(
        device_type=device_type,
        selected_source=selected_source,
        interval_ms=interval_ms,
        expected_eval_samples=eval_expected,
        latency_p95=percentile(latencies, 95),
        latency_p99=percentile(latencies, 99),
        jitter_p95=percentile(jitters, 95),
        monitor_cpu_pct_p95=(
            percentile(cpu_pct_samples[warmup_loops:], 95)
            if cpu_pct_samples[warmup_loops:]
            else 0.0
        ),
        fail_rate=fail_rate,
        rss_delta_mb=rss_delta_mb,
        sample_count=eval_samples,
        quality_bad_count=quality_bad_count,
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Power monitor acceptance benchmark"
    )
    parser.add_argument(
        "--device",
        default="x86_edge",
        choices=["jetson_nano", "rpi4b", "x86_edge"],
    )
    parser.add_argument("--source", default="dummy", choices=["dummy", "sysfs"])
    parser.add_argument("--interval-ms", type=int, default=1000)
    parser.add_argument(
        "--duration-sec",
        type=int,
        default=720,
        help="Total duration in seconds (default 12min)",
    )
    parser.add_argument(
        "--warmup-sec",
        type=int,
        default=120,
        help="Warmup duration in seconds (default 2min)",
    )
    parser.add_argument("--report-json", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.duration_sec <= args.warmup_sec:
        raise SystemExit("duration-sec must be greater than warmup-sec")

    result = run_acceptance(
        device_type=args.device,
        source_name=args.source,
        interval_ms=args.interval_ms,
        duration_sec=args.duration_sec,
        warmup_sec=args.warmup_sec,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["pass"]:
        print("PASS")
    else:
        print("FAIL")
        for reason in result["reasons"]:
            print(f"- {reason}")

    if args.report_json:
        Path(args.report_json).write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
