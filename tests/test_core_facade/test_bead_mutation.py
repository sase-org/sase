"""Parity tests for the Rust bead mutation facade."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.config import save_config
from sase.bead.model import IssueType, Status
from sase.bead.project import AlreadyReadyError, BeadProject, NotAPlanError
from sase.core import bead_mutation_facade as rust_beads


def test_mutation_facade_jsonl_matches_python_after_each_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    py_root = tmp_path / "py"
    rust_root = tmp_path / "rust"
    _init_store(py_root)
    _init_store(rust_root)

    with BeadProject(py_root) as project:
        monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:00:00Z")
        py_epic = project.create("Epic", IssueType.PLAN, description="Plan")
        rust_epic, outcome = rust_beads.create(
            rust_root / "sdd/beads",
            title="Epic",
            issue_type=IssueType.PLAN,
            description="Plan",
            now="2026-01-01T00:00:00Z",
        )
        assert rust_epic.id == py_epic.id
        assert outcome["operation"] == "create"
        _assert_jsonl_equal(py_root, rust_root)

        monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:01:00Z")
        py_child = project.create(
            "Child",
            IssueType.PHASE,
            parent_id=py_epic.id,
            assignee="alice",
        )
        rust_child, _ = rust_beads.create(
            rust_root / "sdd/beads",
            title="Child",
            issue_type=IssueType.PHASE,
            parent_id=rust_epic.id,
            assignee="alice",
            now="2026-01-01T00:01:00Z",
        )
        assert rust_child.id == py_child.id
        _assert_jsonl_equal(py_root, rust_root)

        monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:02:00Z")
        project.add_dependency(py_child.id, py_epic.id)
        rust_dep, _ = rust_beads.add_dependency(
            rust_root / "sdd/beads",
            rust_child.id,
            rust_epic.id,
            now="2026-01-01T00:02:00Z",
        )
        assert rust_dep.depends_on_id == rust_epic.id
        _assert_jsonl_equal(py_root, rust_root)

        monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:03:00Z")
        project.update(py_child.id, status="in_progress", assignee="bob")
        rust_updated, _ = rust_beads.update(
            rust_root / "sdd/beads",
            rust_child.id,
            status="in_progress",
            assignee="bob",
            now="2026-01-01T00:03:00Z",
        )
        assert rust_updated.status == Status.IN_PROGRESS
        _assert_jsonl_equal(py_root, rust_root)

        monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:04:00Z")
        project.update(py_child.id, status="open")
        rust_opened, _ = rust_beads.open_issue(
            rust_root / "sdd/beads",
            rust_child.id,
            now="2026-01-01T00:04:00Z",
        )
        assert rust_opened.status == Status.OPEN
        _assert_jsonl_equal(py_root, rust_root)

        monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:05:00Z")
        py_closed = project.close([py_epic.id], reason="done")
        rust_closed, _ = rust_beads.close(
            rust_root / "sdd/beads",
            [rust_epic.id],
            reason="done",
            now="2026-01-01T00:05:00Z",
        )
        assert [issue.id for issue in rust_closed] == [issue.id for issue in py_closed]
        _assert_jsonl_equal(py_root, rust_root)

        py_removed = project.remove(py_epic.id)
        rust_removed, _ = rust_beads.remove(rust_root / "sdd/beads", rust_epic.id)
        assert [issue.id for issue in rust_removed] == [
            issue.id for issue in py_removed
        ]
        _assert_jsonl_equal(py_root, rust_root)


def test_ready_to_work_errors_map_to_python_exceptions(tmp_path: Path) -> None:
    root = tmp_path / "rust"
    _init_store(root)
    epic, _ = rust_beads.create(
        root / "sdd/beads",
        title="Epic",
        issue_type=IssueType.PLAN,
        now="2026-01-01T00:00:00Z",
    )
    child, _ = rust_beads.create(
        root / "sdd/beads",
        title="Child",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        now="2026-01-01T00:01:00Z",
    )

    with pytest.raises(NotAPlanError):
        rust_beads.mark_ready_to_work(root / "sdd/beads", child.id)

    marked, _ = rust_beads.mark_ready_to_work(
        root / "sdd/beads",
        epic.id,
        now="2026-01-01T00:02:00Z",
    )
    assert marked.is_ready_to_work is True

    with pytest.raises(AlreadyReadyError):
        rust_beads.mark_ready_to_work(root / "sdd/beads", epic.id)

    unmarked, _ = rust_beads.unmark_ready_to_work(
        root / "sdd/beads",
        epic.id,
        now="2026-01-01T00:03:00Z",
    )
    assert unmarked.is_ready_to_work is False


def _init_store(root: Path) -> None:
    with BeadProject.init(root):
        pass
    save_config(
        root / "sdd/beads",
        {"issue_prefix": "gold", "next_counter": 1, "owner": "owner@example.com"},
    )


def _assert_jsonl_equal(left_root: Path, right_root: Path) -> None:
    assert (left_root / "sdd/beads" / "issues.jsonl").read_text() == (
        right_root / "sdd/beads" / "issues.jsonl"
    ).read_text()
