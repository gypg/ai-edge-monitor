"""Report rendering: matplotlib primary, stdlib PNG fallback.

`plot_report(data, output_path)` accepts either a `WindowSummary`
dataclass or a plain dict produced by
`AggregatorAnalyzer.get_summary_dict()`. The matplotlib path produces a
human-readable chart; the stdlib fallback produces a minimal but valid
PNG so the e2e pipeline still runs on hosts without matplotlib.

Both paths write a sidecar `.json` next to the PNG so reviewers can see
the exact summary the chart was rendered from. Returns the path written.
"""

from __future__ import annotations

import dataclasses
import io
import json
import logging
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

LOG = logging.getLogger("visualizer")


_PathLike = Union[str, Path]


def plot_report(data: Union[Dict[str, Any], Any], output_path: _PathLike) -> str:
    """Write a PNG report at `output_path`. Returns the resolved path.

    `data` may be a dict (preferred — JSON-friendly) or a WindowSummary
    dataclass; this function converts to dict internally.
    """
    payload = _coerce_to_dict(data)
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    sidecar = out.with_suffix(out.suffix + ".json") if out.suffix else out.with_suffix(".json")
    sidecar.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    backend = _try_matplotlib_backend(payload, out)
    if backend is None:
        LOG.info("matplotlib unavailable — using stdlib PNG fallback")
        _stdlib_png_backend(payload, out)
        backend = "stdlib"
    else:
        LOG.info("rendered report with matplotlib backend")

    payload["_render_backend"] = backend
    sidecar.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(out)


def _coerce_to_dict(data: Any) -> Dict[str, Any]:
    if isinstance(data, dict):
        return dict(data)
    if dataclasses.is_dataclass(data):
        return dataclasses.asdict(data)
    raise TypeError(f"plot_report expects dict or dataclass, got {type(data).__name__}")


def _try_matplotlib_backend(data: Dict[str, Any], out: Path) -> Optional[str]:
    try:
        import matplotlib  # type: ignore
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore
    except Exception:
        return None

    ts_ms: List[int] = list(data.get("timeline_ts_ms") or [])
    cpu: List[float] = list(data.get("timeline_cpu") or [])
    mem: List[float] = list(data.get("timeline_mem_used_mb") or [])
    p_ts_ms: List[int] = list(data.get("timeline_power_ts_ms") or [])
    p_w: List[float] = list(data.get("timeline_power_watt") or [])

    fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(10, 6), constrained_layout=True)
    fig.suptitle("AI Edge Monitor — Window Summary")

    if ts_ms and cpu:
        t0 = ts_ms[0]
        x_cpu = [(t - t0) / 1000.0 for t in ts_ms]
        ax_top.plot(x_cpu, cpu, color="tab:blue", label="CPU %")
    ax_top.set_xlabel("seconds since window start")
    ax_top.set_ylabel("CPU %", color="tab:blue")
    ax_top.tick_params(axis="y", labelcolor="tab:blue")
    ax_top.set_ylim(0, 100)

    ax_top_r = ax_top.twinx()
    if p_ts_ms and p_w:
        t0p = p_ts_ms[0] if not ts_ms else ts_ms[0]
        x_p = [(t - t0p) / 1000.0 for t in p_ts_ms]
        ax_top_r.plot(x_p, p_w, color="tab:red", label="Power W")
    ax_top_r.set_ylabel("Power (W)", color="tab:red")
    ax_top_r.tick_params(axis="y", labelcolor="tab:red")

    if ts_ms and mem:
        t0 = ts_ms[0]
        x_mem = [(t - t0) / 1000.0 for t in ts_ms]
        ax_bot.plot(x_mem, mem, color="tab:green", label="Memory used (MB)")
    ax_bot.set_xlabel("seconds since window start")
    ax_bot.set_ylabel("Memory used (MB)")
    ax_bot.grid(True, alpha=0.3)

    summary_text = (
        f"window={data.get('window_sec')}s  "
        f"cpu_avg={_fmt(data.get('cpu_avg'))}%  "
        f"cpu_p95={_fmt(data.get('cpu_p95'))}%  "
        f"power_avg={_fmt(data.get('power_avg_watt'))}W  "
        f"power_p95={_fmt(data.get('power_p95_watt'))}W  "
        f"energy={_fmt(data.get('energy_joule'))}J  "
        f"quality={data.get('power_quality_worst')}"
    )
    fig.text(0.01, 0.01, summary_text, fontsize=9)

    fig.savefig(str(out), dpi=110)
    plt.close(fig)
    return "matplotlib"


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# Stdlib PNG fallback
# ---------------------------------------------------------------------------

_WIDTH = 800
_HEIGHT = 400
_BG = (255, 255, 255)
_AXIS = (40, 40, 40)
_CPU_COLOR = (33, 102, 172)   # blue
_POWER_COLOR = (203, 24, 29)  # red
_MEM_COLOR = (35, 139, 69)    # green
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 60, 30, 30, 40


def _stdlib_png_backend(data: Dict[str, Any], out: Path) -> None:
    pixels = bytearray(_WIDTH * _HEIGHT * 3)
    for i in range(0, len(pixels), 3):
        pixels[i:i+3] = bytes(_BG)

    _draw_axes(pixels)

    cpu_x, cpu_y = _project_series(
        data.get("timeline_ts_ms") or [],
        data.get("timeline_cpu") or [],
        y_min=0.0, y_max=100.0,
    )
    _draw_polyline(pixels, cpu_x, cpu_y, _CPU_COLOR)

    power_xs = data.get("timeline_power_ts_ms") or []
    power_ys = data.get("timeline_power_watt") or []
    if power_ys:
        ymax = max(power_ys) * 1.1 if max(power_ys) > 0 else 1.0
        p_x, p_y = _project_series(power_xs, power_ys, y_min=0.0, y_max=ymax)
        _draw_polyline(pixels, p_x, p_y, _POWER_COLOR)

    mem_ys = data.get("timeline_mem_used_mb") or []
    if mem_ys:
        mem_max = max(mem_ys) * 1.1 if max(mem_ys) > 0 else 1.0
        m_x, m_y = _project_series(
            data.get("timeline_ts_ms") or [], mem_ys,
            y_min=0.0, y_max=mem_max,
        )
        _draw_polyline(pixels, m_x, m_y, _MEM_COLOR)

    _write_png(out, _WIDTH, _HEIGHT, bytes(pixels))


def _draw_axes(pixels: bytearray) -> None:
    for x in range(_PAD_L, _WIDTH - _PAD_R):
        _set_pixel(pixels, x, _HEIGHT - _PAD_B, _AXIS)
    for y in range(_PAD_T, _HEIGHT - _PAD_B):
        _set_pixel(pixels, _PAD_L, y, _AXIS)


def _project_series(
    ts: Sequence[int], ys: Sequence[float],
    y_min: float, y_max: float,
) -> Tuple[List[int], List[int]]:
    if not ts or not ys or len(ts) != len(ys):
        return [], []
    t0, t1 = ts[0], ts[-1]
    x_span = max(1, t1 - t0)
    y_span = max(1e-9, y_max - y_min)
    plot_w = _WIDTH - _PAD_L - _PAD_R
    plot_h = _HEIGHT - _PAD_T - _PAD_B

    xs_px: List[int] = []
    ys_px: List[int] = []
    for t, y in zip(ts, ys):
        nx = (t - t0) / x_span
        ny = (max(y_min, min(y_max, y)) - y_min) / y_span
        x_px = _PAD_L + int(nx * plot_w)
        y_px = (_HEIGHT - _PAD_B) - int(ny * plot_h)
        xs_px.append(x_px)
        ys_px.append(y_px)
    return xs_px, ys_px


def _draw_polyline(pixels: bytearray, xs: Sequence[int], ys: Sequence[int],
                   color: Tuple[int, int, int]) -> None:
    if len(xs) < 2:
        if len(xs) == 1:
            _set_pixel(pixels, xs[0], ys[0], color)
        return
    for i in range(len(xs) - 1):
        _draw_line(pixels, xs[i], ys[i], xs[i+1], ys[i+1], color)


def _draw_line(pixels: bytearray, x0: int, y0: int, x1: int, y1: int,
               color: Tuple[int, int, int]) -> None:
    # Bresenham's line algorithm.
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        _set_pixel(pixels, x0, y0, color)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _set_pixel(pixels: bytearray, x: int, y: int, color: Tuple[int, int, int]) -> None:
    if x < 0 or x >= _WIDTH or y < 0 or y >= _HEIGHT:
        return
    idx = (y * _WIDTH + x) * 3
    pixels[idx:idx+3] = bytes(color)


def _write_png(path: Path, width: int, height: int, raw_rgb: bytes) -> None:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)

    # Per-row filter byte (0 = none) prepended to each row.
    raw = io.BytesIO()
    stride = width * 3
    for y in range(height):
        raw.write(b"\x00")
        raw.write(raw_rgb[y * stride : (y + 1) * stride])
    idat = zlib.compress(raw.getvalue(), 6)

    with open(path, "wb") as fh:
        fh.write(sig)
        _write_chunk(fh, b"IHDR", ihdr)
        _write_chunk(fh, b"IDAT", idat)
        _write_chunk(fh, b"IEND", b"")


def _write_chunk(fh, kind: bytes, data: bytes) -> None:
    fh.write(struct.pack(">I", len(data)))
    fh.write(kind)
    fh.write(data)
    fh.write(struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
