from __future__ import annotations

import argparse
import math
import time
from typing import List, Optional


def run_workload(duration_sec: int = 20, size: int = 64, progress_interval_sec: int = 5) -> int:
    if duration_sec <= 0:
        raise ValueError("duration_sec must be > 0")
    if size <= 0:
        raise ValueError("size must be > 0")
    if progress_interval_sec <= 0:
        raise ValueError("progress_interval_sec must be > 0")

    left = _make_matrix(size, phase=0.0)
    right = _make_matrix(size, phase=1.0)
    scratch: List[float] = []
    started = time.monotonic()
    next_progress = started
    iterations = 0
    checksum = 0.0

    while True:
        now = time.monotonic()
        elapsed = now - started
        if elapsed >= duration_sec:
            break
        phase = elapsed / max(1.0, float(duration_sec))
        checksum += _matmul_checksum(left, right, phase)
        if iterations % 4 == 0:
            scratch = [math.sin(phase + i / 100.0) for i in range(size * 128)]
        elif iterations % 4 == 2:
            scratch = scratch[: max(1, len(scratch) // 2)]
        iterations += 1
        if now >= next_progress:
            print(
                f"inference demo: elapsed={elapsed:.1f}s iterations={iterations} "
                f"scratch={len(scratch)} checksum={checksum:.3f}",
                flush=True,
            )
            next_progress = now + progress_interval_sec

    print(
        f"inference demo complete: duration={duration_sec}s iterations={iterations} "
        f"checksum={checksum:.3f}",
        flush=True,
    )
    return iterations


def _make_matrix(size: int, phase: float) -> List[List[float]]:
    return [[math.sin((r + 1) * (c + 1) * 0.01 + phase) for c in range(size)] for r in range(size)]


def _matmul_checksum(left: List[List[float]], right: List[List[float]], phase: float) -> float:
    size = len(left)
    total = 0.0
    stride = max(1, size // 8)
    for r in range(0, size, stride):
        for c in range(0, size, stride):
            cell = 0.0
            for k in range(size):
                cell += left[r][k] * right[k][c]
            total += math.tanh(cell + phase)
    return total


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="inference_demo")
    parser.add_argument("--duration-sec", type=int, default=20)
    parser.add_argument("--size", type=int, default=64)
    parser.add_argument("--progress-interval-sec", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    run_workload(args.duration_sec, args.size, args.progress_interval_sec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
