import unittest


class TestPowerAcceptanceScript(unittest.TestCase):
    def test_module_exposes_dummy_source_and_evaluator(self):
        from tools import power_acceptance as pa

        self.assertTrue(hasattr(pa, "DummySource"))
        self.assertTrue(hasattr(pa, "evaluate_thresholds"))


if __name__ == "__main__":
    unittest.main()
