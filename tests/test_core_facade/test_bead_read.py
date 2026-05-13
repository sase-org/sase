"""Parity tests for the Rust bead read facade."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sase.bead.model import Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.core import bead_read_facade as rust_beads

GOLDEN = Path(__file__).parents[1] / "test_bead" / "golden"


def _ids(issues: list[Issue]) -> list[str]:
    return [issue.id for issue in issues]


@pytest.fixture
def bead_store(tmp_path: Path) -> tuple[BeadProject, Path, dict[str, Issue]]:
    shutil.copytree(GOLDEN / "stores" / "current", tmp_path / "sdd/beads")
    project = BeadProject(tmp_path)
    return (
        project,
        tmp_path / "sdd/beads",
        {
            "epic": project.show("beads-1"),
            "first": project.show("beads-1.1"),
            "second": project.show("beads-1.2"),
            "other": project.show("beads-3"),
        },
    )


def test_read_facade_matches_bead_project_queries(
    bead_store: tuple[BeadProject, Path, dict[str, Issue]],
) -> None:
    project, beads_dir, issues = bead_store
    try:
        assert rust_beads.show(beads_dir, issues["epic"].id) == project.show(
            issues["epic"].id
        )
        assert _ids(rust_beads.list_issues(beads_dir)) == _ids(project.list_issues())
        assert _ids(rust_beads.list_issues(beads_dir, statuses=[Status.OPEN])) == _ids(
            project.list_issues(statuses=[Status.OPEN])
        )
        assert _ids(
            rust_beads.list_issues(beads_dir, issue_types=[IssueType.PLAN])
        ) == _ids(project.list_issues(issue_types=[IssueType.PLAN]))
        assert _ids(rust_beads.ready(beads_dir)) == _ids(project.ready())
        assert _ids(rust_beads.blocked(beads_dir)) == _ids(project.blocked())
        assert rust_beads.stats(beads_dir) == project.stats()
        assert _ids(rust_beads.get_epic_children(beads_dir, issues["epic"].id)) == _ids(
            project.get_epic_children(issues["epic"].id)
        )
    finally:
        project.__exit__()


def test_read_facade_missing_issue_raises_key_error(
    bead_store: tuple[BeadProject, Path, dict[str, Issue]],
) -> None:
    project, beads_dir, _ = bead_store
    try:
        with pytest.raises(KeyError, match="Issue not found"):
            rust_beads.show(beads_dir, "missing")
    finally:
        project.__exit__()


def test_doctor_reads_jsonl_without_requiring_sqlite(tmp_path: Path) -> None:
    beads_dir = tmp_path / "sdd/beads"
    with BeadProject.init(tmp_path) as project:
        project.create("Epic", IssueType.PLAN)
    (beads_dir / "beads.db").unlink()

    assert rust_beads.list_issues(beads_dir)
    assert rust_beads.doctor(beads_dir) == ["WARNING: beads.db missing"]
