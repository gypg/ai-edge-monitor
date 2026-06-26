"""Shared fixtures for P1-P3 integration tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def src_path():
    """Return the src/ directory path, already on sys.path."""
    return SRC
