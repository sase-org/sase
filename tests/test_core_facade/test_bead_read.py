"""Parity tests for the Rust bead read facade."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sase.bead.model import Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.bead.workspace import MergedBeadView
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


def test_merged_workspace_facade_matches_python_view(tmp_path: Path) -> None:
    primary = tmp_path / "project" / "sdd/beads"
    secondary = tmp_path / "project_2" / "sdd/beads"
    primary.mkdir(parents=True)
    secondary.mkdir(parents=True)

    _write_issues(
        primary,
        [
            _issue("merge-1", "Old Epic", "2026-01-01T00:00:00Z"),
            _issue(
                "merge-1.1",
                "Blocked",
                "2026-01-01T00:01:00Z",
                issue_type="phase",
                parent_id="merge-1",
                dependencies=[
                    {
                        "issue_id": "merge-1.1",
                        "depends_on_id": "merge-2",
                        "created_at": "2026-01-01T00:01:00Z",
                        "created_by": "",
                    }
                ],
            ),
            _issue("merge-2", "Blocker", "2026-01-01T00:02:00Z"),
        ],
    )
    _write_issues(
        secondary,
        [_issue("merge-1", "New Epic", "2026-01-01T00:03:00Z")],
    )

    beads_dirs = [primary, secondary]
    with MergedBeadView(beads_dirs) as python_view:
        assert rust_beads.merged_show(beads_dirs, "merge-1").title == "New Epic"
        assert _ids(rust_beads.merged_list_issues(beads_dirs)) == _ids(
            python_view.list_issues()
        )
        assert _ids(rust_beads.merged_ready(beads_dirs)) == _ids(python_view.ready())
        assert _ids(rust_beads.merged_blocked(beads_dirs)) == _ids(
            python_view.blocked()
        )
        assert rust_beads.merged_stats(beads_dirs) == python_view.stats()
        assert _ids(rust_beads.merged_get_epic_children(beads_dirs, "merge-1")) == _ids(
            python_view.get_epic_children("merge-1")
        )


def _write_issues(beads_dir: Path, issues: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(issue, separators=(",", ":")) + "\n" for issue in issues)
    (beads_dir / "issues.jsonl").write_text(text, encoding="utf-8")


def _issue(
    issue_id: str,
    title: str,
    updated_at: str,
    *,
    issue_type: str = "plan",
    parent_id: str | None = None,
    dependencies: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": issue_id,
        "title": title,
        "status": "open",
        "issue_type": issue_type,
        "parent_id": parent_id,
        "owner": "",
        "assignee": "",
        "created_at": updated_at,
        "created_by": "",
        "updated_at": updated_at,
        "closed_at": None,
        "close_reason": None,
        "description": "",
        "notes": "",
        "design": "",
        "is_ready_to_work": False,
        "changespec_name": "",
        "changespec_bug_id": "",
        "dependencies": dependencies or [],
    }
