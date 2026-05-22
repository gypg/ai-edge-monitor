from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from storage_exporter import CsvExporter, JsonlExporter, SummaryExporter


class StorageExporterTests(unittest.TestCase):
    def test_jsonl_exporter_appends_one_json_object_per_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exporter = JsonlExporter(tmp)
            first = {"ts_ms": 1, "cpu_percent": 12.5, "status": "ok"}
            second = {"ts_ms": 2, "cpu_percent": 13.5, "status": "ok"}

            first_path = exporter.write_metrics([first])
            second_path = exporter.write_metrics([second])

            self.assertEqual(first_path, second_path)
            lines = Path(first_path).read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(line) for line in lines], [first, second])

    def test_jsonl_exporter_skips_empty_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = JsonlExporter(tmp).write_metrics([])

            self.assertEqual(path, Path(tmp) / "metrics.jsonl")
            self.assertFalse(path.exists())

    def test_csv_exporter_writes_header_and_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metrics = [
                {"ts_ms": 1, "cpu_percent": 12.5, "status": "ok"},
                {"ts_ms": 2, "cpu_percent": 13.5, "status": "ok"},
            ]

            path = CsvExporter(tmp).write_metrics(metrics)

            with Path(path).open("r", encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(rows[0]["ts_ms"], "1")
            self.assertEqual(rows[0]["cpu_percent"], "12.5")
            self.assertEqual(rows[1]["status"], "ok")

    def test_csv_exporter_skips_empty_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = CsvExporter(tmp).write_metrics([])

            self.assertEqual(path, Path(tmp) / "metrics.csv")
            self.assertFalse(path.exists())

    def test_summary_exporter_writes_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = {"sample_count_metrics": 2, "cpu_avg": 13.0}

            path = SummaryExporter(tmp).write_summary(summary)

            self.assertEqual(json.loads(Path(path).read_text(encoding="utf-8")), summary)

    def test_summary_exporter_skips_empty_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = SummaryExporter(tmp).write_summary({})

            self.assertEqual(path, Path(tmp) / "summary.json")
            self.assertFalse(path.exists())

    def test_exporters_raise_clear_error_when_output_path_is_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "not_a_directory"
            file_path.write_text("occupied", encoding="utf-8")

            with self.assertRaisesRegex(OSError, "output path is not a directory"):
                JsonlExporter(file_path).write_metrics([{"ts_ms": 1}])


if __name__ == "__main__":
    unittest.main()
