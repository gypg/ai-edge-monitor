"""visualizer — lightweight reporting layer.

Public API:
    plot_report(data, output_path)  — write a PNG report and JSON sidecar.

CLI:
    python -m visualizer --input summary.json --output report.png

Backends:
    1. Matplotlib (preferred). Produces a dual-Y-axis line chart of CPU%
       and Power(W) over time, with a memory subplot.
    2. Stdlib fallback. Renders a tiny RGB PNG with two colored lines on
       a white background, written via the stdlib `zlib` + manual PNG
       chunk encoding. Used on hosts without matplotlib (e.g. minimal
       embedded edges, this dev box). The fallback is functionally
       complete enough for CI smoke tests to confirm the report pipeline
       runs end-to-end; on real edge devices we still recommend
       installing matplotlib for human review.
"""

from .report import plot_report

__all__ = ["plot_report"]
