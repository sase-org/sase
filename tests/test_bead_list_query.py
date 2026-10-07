"""Tests for the indexed list page, closed IDs, and status multi-get."""

from __future__ import annotations

from pathlib import Path

from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.core import bead_read_facade as rust_beads


def _seed(tmp_path: Path) -> BeadProject:
    project = BeadProject.init(tmp_path, beads_dirname="beads")
    return project


def test_list_issue_page_returns_total_and_newest_slice(tmp_path: Path) -> None:
    with _seed(tmp_path) as project:
        first = project.create("First", IssueType.PLAN)
        second = project.create("Second", IssueType.PLAN)
        project.update(second.id, status="closed")

        total, issues = project.list_issue_page(statuses=[Status.CLOSED], limit=20)
        assert total == 1
        assert [issue.id for issue in issues] == [second.id]

        total, issues = project.list_issue_page(limit=1)
        assert total == 2
        assert [issue.id for issue in issues] == [second.id]

        total, issues = project.list_issue_page(limit=0)
        assert total == 2
        assert [issue.id for issue in issues] == [first.id, second.id]


def test_list_issue_page_task_type_filter(tmp_path: Path) -> None:
    with _seed(tmp_path) as project:
        project.create("Bug", IssueType.TASK, task_type="bug", size="small")
        project.create("Feature", IssueType.TASK, task_type="feature", size="small")

        total, issues = project.list_issue_page(task_types=["bug"])
        assert total == 1
        assert [issue.title for issue in issues] == ["Bug"]

        total, issues = project.list_issue_page(task_types=[""])
        assert total == 0
        assert issues == []


def test_closed_ids_lists_closed_beads(tmp_path: Path) -> None:
    with _seed(tmp_path) as project:
        open_issue = project.create("Open", IssueType.PLAN)
        closed_issue = project.create("Closed", IssueType.PLAN)
        project.update(closed_issue.id, status="closed")

        assert rust_beads.closed_ids(project.beads_dir) == [closed_issue.id]
        assert open_issue.id not in rust_beads.closed_ids(project.beads_dir)


def test_statuses_for_ids_omits_unknown_and_ambiguous(tmp_path: Path) -> None:
    with _seed(tmp_path) as project:
        issue = project.create("Claimed", IssueType.PLAN)
        project.update(issue.id, status="claimed")

        assert rust_beads.statuses_for_ids(
            project.beads_dir, [issue.id, "missing"]
        ) == {issue.id: "claimed"}
        suffix = issue.id.rsplit("-", 1)[-1]
        assert rust_beads.statuses_for_ids(project.beads_dir, [suffix]) == {
            suffix: "claimed"
        }
        assert rust_beads.statuses_for_ids(project.beads_dir, []) == {}
