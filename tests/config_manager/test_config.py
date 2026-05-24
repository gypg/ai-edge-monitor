from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config_manager import ConfigError, MonitorConfig, load_config


class ConfigManagerTests(unittest.TestCase):
    def test_default_config_values(self) -> None:
        config = load_config()

        self.assertEqual(config.duration_sec, 30)
        self.assertEqual(config.interval_ms, 1000)
        self.assertEqual(config.output_dir, "reports/demo")
        self.assertEqual(config.device, "auto")
        self.assertFalse(config.force_dummy)
        self.assertEqual(config.exporters, ("jsonl", "csv", "summary", "png"))
        self.assertEqual(config.thresholds["cpu_high"], 85.0)
        self.assertEqual(config.thresholds["temp_high"], 80.0)

    def test_loads_yaml_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.yaml"
            path.write_text(
                "\n".join(
                    [
                        "duration_sec: 12",
                        "interval_ms: 250",
                        "output_dir: reports/custom",
                        "device: nvidia-smi",
                        "force_dummy: true",
                        "exporters:",
                        "  - jsonl",
                        "  - summary",
                        "thresholds:",
                        "  cpu_high: 70",
                        "  temp_high: 75.5",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(path)

            self.assertEqual(config.duration_sec, 12)
            self.assertEqual(config.interval_ms, 250)
            self.assertEqual(config.output_dir, "reports/custom")
            self.assertEqual(config.device, "nvidia-smi")
            self.assertTrue(config.force_dummy)
            self.assertEqual(config.exporters, ("jsonl", "summary"))
            self.assertEqual(config.thresholds["cpu_high"], 70.0)
            self.assertEqual(config.thresholds["temp_high"], 75.5)

    def test_cli_overrides_file_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.yaml"
            path.write_text(
                "duration_sec: 12\ninterval_ms: 250\nforce_dummy: false\n",
                encoding="utf-8",
            )

            config = load_config(
                path,
                overrides={"duration_sec": 5, "output_dir": "reports/override", "force_dummy": True},
            )

            self.assertEqual(config.duration_sec, 5)
            self.assertEqual(config.interval_ms, 250)
            self.assertEqual(config.output_dir, "reports/override")
            self.assertTrue(config.force_dummy)

    def test_unknown_key_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitor.yaml"
            path.write_text("unexpected: true\n", encoding="utf-8")

            with self.assertRaisesRegex(ConfigError, "unknown config key: unexpected"):
                load_config(path)

    def test_invalid_positive_int_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ConfigError, "duration_sec must be > 0"):
            MonitorConfig(duration_sec=0)

    def test_invalid_exporter_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ConfigError, "unsupported exporter: sqlite"):
            MonitorConfig(exporters=("jsonl", "sqlite"))

    def test_invalid_threshold_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ConfigError, "threshold cpu_high must be a number"):
            MonitorConfig(thresholds={"cpu_high": "hot"})


if __name__ == "__main__":
    unittest.main()