from __future__ import annotations

import subprocess
import unittest

from platform_adapter.nvidia_smi_probe import NvidiaSmiProbe, parse_nvidia_smi_csv


class NvidiaSmiProbeTests(unittest.TestCase):
    def test_parse_nvidia_smi_csv_output(self) -> None:
        parsed = parse_nvidia_smi_csv("42, 1024, 8192, 67\n")

        self.assertEqual(parsed.gpu_percent, 42.0)
        self.assertEqual(parsed.gpu_mem_used_mb, 1024.0)
        self.assertEqual(parsed.gpu_mem_total_mb, 8192.0)
        self.assertEqual(parsed.temperature_c, 67.0)

    def test_probe_unavailable_when_command_fails(self) -> None:
        def runner(command, timeout):
            raise FileNotFoundError("nvidia-smi")

        probe = NvidiaSmiProbe(runner=runner)

        self.assertFalse(probe.is_available())
        caps = probe.detect_caps()
        self.assertFalse(caps.has_gpu)
        self.assertIn("nvidia-smi unavailable", caps.notes["error"])

    def test_read_metrics_returns_gpu_values(self) -> None:
        def runner(command, timeout):
            return subprocess.CompletedProcess(command, 0, "42, 1024, 8192, 67\n", "")

        probe = NvidiaSmiProbe(runner=runner)

        metrics = probe.read_metrics()

        self.assertEqual(metrics.status, "ok")
        self.assertEqual(metrics.probe_name, "nvidia-smi")
        self.assertEqual(metrics.gpu_percent, 42.0)
        self.assertEqual(metrics.gpu_mem_used_mb, 1024.0)
        self.assertEqual(metrics.temperature_c, 67.0)

    def test_read_metrics_returns_parse_error_for_bad_output(self) -> None:
        def runner(command, timeout):
            return subprocess.CompletedProcess(command, 0, "bad output\n", "")

        probe = NvidiaSmiProbe(runner=runner)

        metrics = probe.read_metrics()

        self.assertEqual(metrics.status, "parse_error")
        self.assertIsNone(metrics.gpu_percent)
        self.assertIn("expected 4 CSV fields", metrics.error_message or "")


if __name__ == "__main__":
    unittest.main()
