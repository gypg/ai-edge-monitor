from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Union

OutputPath = Union[str, Path]
MetricRow = Mapping[str, Any]


class JsonlExporter:
    def __init__(self, output_dir: OutputPath) -> None:
        self.output_dir = Path(output_dir)

    def write_metrics(self, metrics: Iterable[MetricRow]) -> Path:
        rows = list(metrics)
        path = self.output_dir / "metrics.jsonl"
        if not rows:
            return path
        _ensure_output_dir(self.output_dir)
        with path.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True))
                fh.write("\n")
        return path


class CsvExporter:
    def __init__(self, output_dir: OutputPath) -> None:
        self.output_dir = Path(output_dir)

    def write_metrics(self, metrics: Iterable[MetricRow]) -> Path:
        rows = [dict(row) for row in metrics]
        path = self.output_dir / "metrics.csv"
        if not rows:
            return path
        _ensure_output_dir(self.output_dir)
        fieldnames = _fieldnames(rows)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path


class SummaryExporter:
    def __init__(self, output_dir: OutputPath) -> None:
        self.output_dir = Path(output_dir)

    def write_summary(self, summary: Mapping[str, Any]) -> Path:
        path = self.output_dir / "summary.json"
        if not summary:
            return path
        _ensure_output_dir(self.output_dir)
        path.write_text(json.dumps(dict(summary), indent=2, ensure_ascii=False), encoding="utf-8")
        return path


def _ensure_output_dir(output_dir: Path) -> None:
    if output_dir.exists() and not output_dir.is_dir():
        raise OSError(f"output path is not a directory: {output_dir}")
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
