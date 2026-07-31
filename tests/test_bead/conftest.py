"""Shared fixtures for bead tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.bead import db
from sase.bead.model import BeadTier, Issue, IssueType
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
def nested_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, Issue]]:
    """Create a nested epic/phase store for bead show tests."""
    with BeadProject.init(tmp_path):
        pass
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.bead.workspace.resolve_primary_workspace", lambda: None)

    plan_paths = {
        name: tmp_path / f"{name}.md"
        for name in ("root", "phase_child", "epic_child", "deep_child")
    }
    for path in plan_paths.values():
        path.write_text(f"# {path.stem}\n", encoding="utf-8")

    with BeadProject(tmp_path) as project:
        root = project.create(
            "Root Epic",
            IssueType.PLAN,
            tier=BeadTier.EPIC,
            design=str(plan_paths["root"]),
        )
        phase = project.create("Root Phase", IssueType.PHASE, parent_id=root.id)
        phase = project.update(phase.id, size="medium")
        childless_phase = project.create(
            "Childless Phase",
            IssueType.PHASE,
            parent_id=root.id,
        )
        phase_child = project.create(
            "Phase Child Epic",
            IssueType.PLAN,
            parent_id=phase.id,
            tier=BeadTier.EPIC,
            design=str(plan_paths["phase_child"]),
        )
        nested_phase = project.create(
            "Nested Phase",
            IssueType.PHASE,
            parent_id=phase_child.id,
        )
        nested_phase = project.update(nested_phase.id, size="large")
        deep_child = project.create(
            "Deep Child Epic",
            IssueType.PLAN,
            parent_id=nested_phase.id,
            tier=BeadTier.EPIC,
            design=str(plan_paths["deep_child"]),
        )
        epic_child = project.create(
            "Epic Child Epic",
            IssueType.PLAN,
            parent_id=root.id,
            tier=BeadTier.EPIC,
            design=str(plan_paths["epic_child"]),
        )

    yield {
        "root": root,
        "phase": phase,
        "childless_phase": childless_phase,
        "phase_child": phase_child,
        "nested_phase": nested_phase,
        "deep_child": deep_child,
        "epic_child": epic_child,
    }


@pytest.fixture
def fake_cli_work_xprompts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub xprompt resolution for ``sase bead work`` CLI tests."""
    work_phase = Workflow(name="bd/work_phase_bead")
    work_task = Workflow(name="bd/work_task")
    land_epic = Workflow(name="bd/land_epic")
    monkeypatch.setattr(
        "sase.bead.xprompts.resolve_work_phase_xprompt",
        lambda project=None: work_phase,
    )
    monkeypatch.setattr(
        "sase.bead.xprompts.resolve_work_task_xprompt",
        lambda project=None: work_task,
    )
    monkeypatch.setattr(
        "sase.bead.xprompts.resolve_land_epic_xprompt",
        lambda project=None: land_epic,
    )
