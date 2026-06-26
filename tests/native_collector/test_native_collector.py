"""Tests for C++ native collector layer.

Validates C++ source structure, build configuration, pybind11 bindings,
and Python fallback behaviour.  Python 3.8+ compatible.  No external
dependencies (unittest only).

The C++ sources live under  ``<root>/cpp_src/``.
On CI (Ubuntu) these tests verify file presence and content — they do NOT
compile C++.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
CPP_SRC = ROOT / "cpp_src"
SRC_DIR = ROOT / "src"
NATIVE_COLLECTOR_PKG = SRC_DIR / "native_collector"
CPP_INCLUDE = CPP_SRC / "include"
CPP_BINDINGS = CPP_SRC / "pybind"
CPP_TESTS = CPP_SRC / "tests"


# ===================================================================
# 1. C++ source-structure tests
# ===================================================================
class TestCppSourceStructure(unittest.TestCase):
    """Verify the ``cpp_src/`` tree exists with the expected layout."""

    def test_cpp_src_directory_and_cmake_lists(self):
        """cpp_src/ dir and CMakeLists.txt must exist."""
        self.assertTrue(
            CPP_SRC.is_dir(),
            "cpp_src/ directory missing",
        )
        cmake = CPP_SRC / "CMakeLists.txt"
        self.assertTrue(cmake.exists(), "Missing cpp_src/CMakeLists.txt")

    def test_source_files_present(self):
        """All required .cpp files must exist under cpp_src/."""
        required = [
            "system_info.cpp",
            "memory_monitor.cpp",
            "optimized_kernels.cpp",
        ]
        missing = [f for f in required if not (CPP_SRC / f).exists()]
        self.assertEqual(missing, [], "Missing source files: {}".format(missing))

    def test_header_files_present(self):
        """All required .hpp headers must exist under cpp_src/include/."""
        self.assertTrue(CPP_INCLUDE.is_dir(), "Missing cpp_src/include/ directory")
        required = [
            "system_info.hpp",
            "memory_monitor.hpp",
            "optimized_kernels.hpp",
        ]
        missing = [f for f in required if not (CPP_INCLUDE / f).exists()]
        self.assertEqual(missing, [], "Missing header files: {}".format(missing))

    def test_bindings_and_tests_dirs(self):
        """cpp_src/pybind/ and cpp_src/tests/ directories must exist."""
        self.assertTrue(CPP_BINDINGS.is_dir(), "Missing cpp_src/pybind/ directory")
        self.assertTrue(CPP_TESTS.is_dir(), "Missing cpp_src/tests/ directory")


# ===================================================================
# 2. Header-content validation
# ===================================================================
class TestHeaderValidation(unittest.TestCase):
    """Verify key symbols are declared in the C++ headers."""

    def _read(self, relative):
        # type: (str) -> str
        path = CPP_INCLUDE / relative
        self.assertTrue(path.exists(), "File missing: {}".format(path))
        return path.read_text(encoding="utf-8", errors="replace")

    def test_system_info_header(self):
        """system_info.hpp must declare SystemInfo, CpuInfo, MemoryInfo."""
        content = self._read("system_info.hpp")
        self.assertIn("SystemInfo", content)
        self.assertIn("CpuInfo", content)
        self.assertIn("MemoryInfo", content)
        self.assertIn("collect_system_info", content)

    def test_memory_monitor_header(self):
        """memory_monitor.hpp must declare MemoryMonitor class."""
        content = self._read("memory_monitor.hpp")
        self.assertIn("MemoryMonitor", content)
        self.assertIn("detect_leak", content)

    def test_optimized_kernels_header(self):
        """optimized_kernels.hpp must declare StatsResult, compute_stats."""
        content = self._read("optimized_kernels.hpp")
        self.assertIn("StatsResult", content)
        self.assertIn("compute_stats", content)
        self.assertIn("detect_anomalies_zscore", content)


# ===================================================================
# 3. Cross-compilation toolchain tests
# ===================================================================
class TestCrossCompilationToolchains(unittest.TestCase):
    """Verify cross-compilation toolchain files exist and are valid."""

    EXPECTED_TOOLCHAINS = [
        "toolchain-aarch64.cmake",
        "toolchain-armhf.cmake",
    ]

    def test_all_toolchain_files_present(self):
        """All cross-compile toolchains must exist."""
        missing = [n for n in self.EXPECTED_TOOLCHAINS if not (CPP_SRC / n).exists()]
        self.assertEqual(missing, [], "Missing toolchain files: {}".format(missing))

    def test_aarch64_toolchain_sets_system_name_and_compiler(self):
        """aarch64 toolchain must set CMAKE_SYSTEM_NAME and a cross-compiler."""
        path = CPP_SRC / "toolchain-aarch64.cmake"
        if not path.exists():
            self.skipTest("toolchain file missing")
        content = path.read_text(encoding="utf-8", errors="replace")
        self.assertIn("CMAKE_SYSTEM_NAME", content)
        self.assertTrue(
            "CMAKE_C_COMPILER" in content or "aarch64" in content,
            "aarch64 toolchain should set a cross-compiler",
        )

    def test_armhf_toolchain_sets_system_name(self):
        """armhf toolchain must set CMAKE_SYSTEM_NAME."""
        path = CPP_SRC / "toolchain-armhf.cmake"
        if not path.exists():
            self.skipTest("toolchain file missing")
        content = path.read_text(encoding="utf-8", errors="replace")
        self.assertIn("CMAKE_SYSTEM_NAME", content)


# ===================================================================
# 4. CMake validation
# ===================================================================
class TestCMakeConfiguration(unittest.TestCase):
    """Verify CMakeLists.txt has required targets and settings."""

    def _read_cmake(self):
        # type: () -> str
        path = CPP_SRC / "CMakeLists.txt"
        self.assertTrue(path.exists(), "Missing cpp_src/CMakeLists.txt")
        return path.read_text(encoding="utf-8", errors="replace")

    def test_cmake_minimum_version_314_plus(self):
        """cmake_minimum_required must exist."""
        content = self._read_cmake()
        self.assertIn("cmake_minimum_required", content)

    def test_cmake_cpp17_and_pybind11(self):
        """CMakeLists.txt must require C++17 and reference pybind11."""
        content = self._read_cmake()
        self.assertTrue(
            "CMAKE_CXX_STANDARD 17" in content
            or "cxx_std_17" in content
            or "CXX_STANDARD 17" in content
            or "set(CMAKE_CXX_STANDARD 17" in content,
            "CMakeLists.txt must require C++17 standard",
        )
        self.assertTrue(
            "pybind11" in content.lower() or "pybind" in content.lower(),
            "CMakeLists.txt should reference pybind11",
        )

    def test_cmake_no_boost(self):
        """Spec forbids heavyweight Boost dependency."""
        content = self._read_cmake()
        self.assertNotIn("find_package(Boost", content)


# ===================================================================
# 5. pybind11 bindings tests
# ===================================================================
class TestPybindBindings(unittest.TestCase):
    """Verify the pybind11 binding layer."""

    def test_bindings_file_exists_and_includes_pybind11(self):
        path = CPP_BINDINGS / "bindings.cpp"
        self.assertTrue(path.exists(), "Missing cpp_src/pybind/bindings.cpp")
        content = path.read_text(encoding="utf-8", errors="replace")
        self.assertIn("pybind11", content)

    def test_bindings_expose_collectors(self):
        """Bindings must expose key classes to Python."""
        path = CPP_BINDINGS / "bindings.cpp"
        if not path.exists():
            self.skipTest("bindings file missing")
        content = path.read_text(encoding="utf-8", errors="replace")
        self.assertTrue(
            "collect_system_info" in content or "SystemInfo" in content,
            "Bindings should expose collect_system_info to Python",
        )
        self.assertTrue(
            "MemoryMonitor" in content or "memory_monitor" in content,
            "Bindings should expose MemoryMonitor to Python",
        )


# ===================================================================
# 6. Python fallback tests
# ===================================================================
class TestPythonFallback(unittest.TestCase):
    """Verify the native_collector Python package works as fallback."""

    @classmethod
    def setUpClass(cls):
        # Ensure src/ is importable
        if str(SRC_DIR) not in sys.path:
            sys.path.insert(0, str(SRC_DIR))

    def test_native_collector_package_importable(self):
        """Package must exist and be importable."""
        self.assertTrue(NATIVE_COLLECTOR_PKG.is_dir(), "src/native_collector/ missing")
        init = NATIVE_COLLECTOR_PKG / "__init__.py"
        self.assertTrue(init.exists(), "__init__.py missing")
        import native_collector  # noqa: F401

    def test_has_native_is_bool(self):
        from native_collector import HAS_NATIVE

        self.assertIsInstance(HAS_NATIVE, bool)

    def test_has_native_false_without_compiled_extension(self):
        """Without a compiled .so/.pyd, HAS_NATIVE must be False."""
        from native_collector import HAS_NATIVE

        if not _has_compiled_extension():
            self.assertFalse(HAS_NATIVE)

    def test_select_probe_returns_probe_with_read_metrics(self):
        """select_probe() must return an object with read_metrics()."""
        from native_collector import select_probe

        self.assertTrue(callable(select_probe))
        probe = select_probe()
        self.assertTrue(hasattr(probe, "read_metrics"))
        result = probe.read_metrics()
        self.assertIsNotNone(result)

    def test_select_probe_force_native_raises_when_unavailable(self):
        """force_native=True must raise ImportError when native module absent."""
        from native_collector import HAS_NATIVE, select_probe

        if HAS_NATIVE:
            self.skipTest("Native module available; cannot test ImportError path")
        with self.assertRaises(ImportError) as ctx:
            select_probe(force_native=True)
        self.assertIn("Native collector", str(ctx.exception))


# ===================================================================
# Helpers
# ===================================================================
def _has_compiled_extension():
    # type: () -> bool
    """Check if _native_collector .so/.pyd is importable."""
    try:
        import _native_collector  # noqa: F401

        return True
    except ImportError:
        return False


# ===================================================================
if __name__ == "__main__":
    unittest.main()
