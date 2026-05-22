import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestPowerAcceptanceScript(unittest.TestCase):
    def test_module_exposes_dummy_source_and_evaluator(self):
        from tools import power_acceptance as pa

        self.assertTrue(hasattr(pa, "DummySource"))
        self.assertTrue(hasattr(pa, "evaluate_thresholds"))


if __name__ == "__main__":
    unittest.main()
