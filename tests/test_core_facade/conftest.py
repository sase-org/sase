"""Shared fixtures for ``sase.core`` facade tests.

Each facade either calls ``sase_core_rs`` directly through the strict
loader (ported operations) or its Python implementation directly
(intentionally unported operations). The file-path
``parse_project_file`` API stays Python-only for compatibility.
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
