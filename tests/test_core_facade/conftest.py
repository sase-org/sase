"""Shared fixtures for ``sase.core`` facade tests.

Each facade should call the existing Python implementation by default and
behave identically to it. Shipped Rust operations configured for backend
dispatch should fail clearly under ``SASE_CORE_BACKEND=rust`` when no Rust
implementation is registered; intentionally unported facade operations fall
back to Python.

When ``sase_core_rs`` is importable, ``parse_project_bytes`` routes to the Rust
binding under ``SASE_CORE_BACKEND=rust`` and dual-run logs a comparison record.
The file-path ``parse_project_file`` API stays Python-only for compatibility.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_core_facade._helpers import (
    ANCESTRY_PROJECT_TEXT,
    SAMPLE_PROJECT_TEXT,
)


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    target = tmp_path / "myproj.gp"
    target.write_text(SAMPLE_PROJECT_TEXT)
    return target


@pytest.fixture
def ancestry_project(tmp_path: Path) -> Path:
    target = tmp_path / "ancestry.gp"
    target.write_text(ANCESTRY_PROJECT_TEXT)
    return target
