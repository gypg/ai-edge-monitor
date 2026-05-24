from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app_orchestrator import Orchestrator
from config_manager import ConfigError, MonitorConfig


class OrchestratorTests(unittest.TestCase):
    def test_dummy_run_generates_all_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = MonitorConfig(
                duration_sec=2,
                interval_ms=500,
                output_dir=str(Path(tmp) / "demo"),
                force_dummy=True,
            )

            result = Orchestrator(config).run()

            self.assertGreaterEqual(result.metrics_count, 2)
            self.assertGreaterEqual(result.power_count, 2)
            for path in (
                result.metrics_jsonl,
                result.metrics_csv,
                result.summary_json,
                result.report_png,
            ):
                self.assertTrue(path.is_file(), f"missing {path}")
                self.assertGreater(path.stat().st_size, 0, f"empty {path}")
            summary = json.loads(result.summary_json.read_text(encoding="utf-8"))
            self.assertEqual(summary["probe_name"], "dummy")
            self.assertEqual(result.report_png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_invalid_output_path_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "not_a_dir"
            file_path.write_text("occupied", encoding="utf-8")
            config = MonitorConfig(
                duration_sec=1,
                interval_ms=500,
                output_dir=str(file_path),
                force_dummy=True,
            )

            with self.assertRaisesRegex(ConfigError, "output path is not a directory"):
                Orchestrator(config).run()


if __name__ == "__main__":
    unittest.main()
