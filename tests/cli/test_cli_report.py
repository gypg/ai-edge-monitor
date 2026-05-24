from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliReportTests(unittest.TestCase):
    def test_report_command_renders_png_from_summary_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = root / "summary.json"
            summary.write_text(
                json.dumps(
                    {
                        "window_sec": 30,
                        "sample_count_metrics": 2,
                        "sample_count_power": 2,
                        "cpu_avg": 12.0,
                        "cpu_p95": 13.0,
                        "cpu_max": 14.0,
                        "timeline_ts_ms": [1000, 2000],
                        "timeline_cpu": [12.0, 14.0],
                        "timeline_mem_used_mb": [512.0, 513.0],
                        "timeline_power_ts_ms": [1000, 2000],
                        "timeline_power_watt": [7.5, 7.8],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "report.png"

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cli",
                    "report",
                    "--input",
                    str(summary),
                    "--out",
                    str(output),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(output.is_file())
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertTrue(output.with_suffix(".png.json").is_file())

    def test_report_command_returns_nonzero_for_missing_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            output = Path(tmp) / "report.png"

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "cli",
                    "report",
                    "--input",
                    str(missing),
                    "--out",
                    str(output),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("error:", proc.stderr.lower())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
