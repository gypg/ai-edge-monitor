"""CLI: python -m visualizer --input summary.json --output report.png"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .report import plot_report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="visualizer")
    parser.add_argument("--input", required=True, help="path to a JSON summary file")
    parser.add_argument("--output", required=True, help="path to write the PNG report")
    args = parser.parse_args(argv)

    src = Path(args.input)
    if not src.is_file():
        print(f"input not found: {src}", file=sys.stderr)
        return 2
    payload = json.loads(src.read_text(encoding="utf-8"))
    out = plot_report(payload, args.output)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
