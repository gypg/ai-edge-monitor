"""Tests for native_collector Python wrapper and fallback logic."""

from __future__ import annotations

import sys
import unittest


class TestNativeCollector(unittest.TestCase):

    def test_import_does_not_crash(self) -> None:
        """Importing native_collector must succeed on any platform."""
        import native_collector  # noqa: F401

    def test_has_native_false_on_windows(self) -> None:
        """On Windows there is no compiled .so/.pyd, so HAS_NATIVE is False."""
        if sys.platform == "win32":
            from native_collector import HAS_NATIVE
            self.assertFalse(HAS_NATIVE)

    def test_select_probe_returns_python_probe(self) -> None:
        """select_probe() without force_native returns a Python-based probe."""
        from native_collector import select_probe

        probe = select_probe()
        # Should have a read_metrics method (PlatformProbe interface)
        self.assertTrue(hasattr(probe, "read_metrics"))

    def test_select_probe_force_native_raises(self) -> None:
        """force_native=True must raise ImportError when native module is absent."""
        from native_collector import HAS_NATIVE, select_probe

        if HAS_NATIVE:
            self.skipTest("Native module is available; cannot test ImportError path")

        with self.assertRaises(ImportError) as cm:
            select_probe(force_native=True)
        self.assertIn("Native collector not available", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
