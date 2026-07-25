"""Shared fixtures for bead tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.bead import db
from sase.bead.project import BeadProject
from sase.xprompt.workflow_models import Workflow
from tests.test_bead.resolution_test_helpers import isolate_bead_store_resolution


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = db.init_db(tmp_path / "test.db")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Create a fresh beads project and route the CLI's lookups at it."""
    with BeadProject.init(tmp_path):
        pass
    isolate_bead_store_resolution(monkeypatch, tmp_path)
    yield tmp_path


@pytest.fixture
def fake_cli_work_xprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub xprompt resolution for ``sase bead work`` CLI tests."""
    work_phase = Workflow(name="bd/work_phase_bead")
    land_epic = Workflow(name="bd/land_epic")
    monkeypatch.setattr(
        "sase.bead.xprompts.resolve_work_phase_xprompt",
        lambda project=None: work_phase,
    )
    monkeypatch.setattr(
        "sase.bead.xprompts.resolve_land_epic_xprompt",
        lambda project=None: land_epic,
    )
