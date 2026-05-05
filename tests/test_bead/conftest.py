"""Shared fixtures for bead tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.bead import db
from sase.bead.project import BeadProject
from sase.xprompt.workflow_models import Workflow


@pytest.fixture
def conn() -> sqlite3.Connection:
    return db.create_memory_db()


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Create a fresh beads project and route the CLI's lookups at it."""
    with BeadProject.init(tmp_path):
        pass
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)
    yield tmp_path


@pytest.fixture
def fake_cli_work_xprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub xprompt resolution for ``sase bead work`` CLI tests."""
    work_phase = Workflow(name="bd/work_phase_bead")
    land_epic = Workflow(name="bd/land_epic")
    land_legend = Workflow(name="bd/land_legend")
    monkeypatch.setattr(
        "sase.bead.xprompts.resolve_work_phase_xprompt",
        lambda project=None: work_phase,
    )
    monkeypatch.setattr(
        "sase.bead.xprompts.resolve_land_epic_xprompt",
        lambda project=None: land_epic,
    )
    monkeypatch.setattr(
        "sase.bead.xprompts.resolve_land_legend_xprompt",
        lambda project=None: land_legend,
    )
