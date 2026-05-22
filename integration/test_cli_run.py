from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliRunIntegrationTests(unittest.TestCase):
    def test_run_command_generates_demo_outputs_with_dummy_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "demo"

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cli",
                    "run",
                    "--duration",
                    "10",
                    "--interval",
                    "1000",
                    "--out",
                    str(out_dir),
                    "--force-dummy",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            metrics_jsonl = out_dir / "metrics.jsonl"
            metrics_csv = out_dir / "metrics.csv"
            summary_json = out_dir / "summary.json"
            report_png = out_dir / "report.png"
            for path in (metrics_jsonl, metrics_csv, summary_json, report_png):
                self.assertTrue(path.is_file(), f"missing {path}; stdout={proc.stdout}")
                self.assertGreater(path.stat().st_size, 0, f"empty {path}")

            lines = metrics_jsonl.read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(len(lines), 2)
            first_metric = json.loads(lines[0])
            self.assertIn("cpu_percent", first_metric)
            self.assertIn("avg_power_watt", first_metric)

            summary = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertGreaterEqual(summary["sample_count_metrics"], 2)
            self.assertGreaterEqual(summary["sample_count_power"], 2)
            self.assertEqual(report_png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
