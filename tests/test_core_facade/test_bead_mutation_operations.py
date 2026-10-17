"""Store-operation tests for the Rust bead mutation facade.

Split from ``tests.test_core_facade.test_bead_mutation``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.core import bead_mutation_facade as rust_beads
from tests.test_core_facade._bead_mutation_helpers import init_store

__all__ = [
    "test_append_note_facade_returns_issue_and_export_reflects_note",
    "test_external_ref_facade_create_update_clear_and_conflict",
    "test_mutation_facade_jsonl_matches_python_after_each_operation",
    "test_mutation_facade_refuses_unsandboxed_pytest_store_before_binding",
    "test_mutation_facade_writes_events_and_repairs_jsonl_projection",
    "test_remove_many_facade_returns_unique_expanded_removals",
    "test_set_link_projections_batch_is_authorized_and_returns_aggregate",
    "test_set_link_projections_refuses_unsandboxed_pytest_store_before_binding",
]


def test_mutation_facade_jsonl_matches_python_after_each_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    py_root = tmp_path / "py"
    rust_root = tmp_path / "rust"
    init_store(py_root)
    init_store(rust_root)

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
        rust_opened, _ = rust_beads.update(
            rust_root / "sdd/beads",
            rust_child.id,
            status="open",
            now="2026-01-01T00:04:00Z",
        )
        assert rust_opened.status == Status.OPEN
        _assert_jsonl_equal(py_root, rust_root)

        monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:05:00Z")
        project.close([py_child.id], reason="done")
        rust_beads.close(
            rust_root / "sdd/beads",
            [rust_child.id],
            reason="done",
            now="2026-01-01T00:05:00Z",
        )
        _assert_jsonl_equal(py_root, rust_root)

        monkeypatch.setattr("sase.bead.project._now", lambda: "2026-01-01T00:06:00Z")
        py_closed = project.close([py_epic.id], reason="done")
        rust_closed, _ = rust_beads.close(
            rust_root / "sdd/beads",
            [rust_epic.id],
            reason="done",
            now="2026-01-01T00:06:00Z",
        )
        assert [issue.id for issue in rust_closed] == [issue.id for issue in py_closed]
        _assert_jsonl_equal(py_root, rust_root)

        py_removed = project.remove(py_epic.id)
        rust_removed, _ = rust_beads.remove(rust_root / "sdd/beads", rust_epic.id)
        assert [issue.id for issue in rust_removed] == [
            issue.id for issue in py_removed
        ]
        _assert_jsonl_equal(py_root, rust_root)


def test_remove_many_facade_returns_unique_expanded_removals(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    init_store(root)
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
    independent, _ = rust_beads.create(
        root / "sdd/beads",
        title="Independent",
        issue_type=IssueType.PLAN,
        now="2026-01-01T00:02:00Z",
    )

    removed, outcome = rust_beads.remove_many(
        root / "sdd/beads",
        [child.id, epic.id, independent.id, child.id],
    )

    assert [issue.id for issue in removed] == [
        child.id,
        epic.id,
        independent.id,
    ]
    assert outcome["operation"] == "rm"
    assert outcome["issue_ids"] == [child.id, epic.id, independent.id]


def test_external_ref_facade_create_update_clear_and_conflict(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    init_store(root)
    first, _ = rust_beads.create(
        root / "sdd/beads",
        title="First",
        issue_type=IssueType.PLAN,
        external_ref="bug:sase#42",
        now="2026-01-01T00:00:00Z",
    )
    second, _ = rust_beads.create(
        root / "sdd/beads",
        title="Second",
        issue_type=IssueType.TASK,
        task_type="bug",
        size="small",
        now="2026-01-01T00:01:00Z",
    )

    assert first.external_ref == "bug:sase#42"
    with pytest.raises(ValueError, match="external_ref bug:sase#42"):
        rust_beads.update(
            root / "sdd/beads",
            second.id,
            external_ref="bug:sase#42",
            now="2026-01-01T00:02:00Z",
        )

    cleared, _ = rust_beads.update(
        root / "sdd/beads",
        first.id,
        external_ref="",
        now="2026-01-01T00:03:00Z",
    )
    assert cleared.external_ref == ""

    updated, _ = rust_beads.update(
        root / "sdd/beads",
        second.id,
        external_ref="bug:sase#42",
        now="2026-01-01T00:04:00Z",
    )
    assert updated.external_ref == "bug:sase#42"


def test_append_note_facade_returns_issue_and_export_reflects_note(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    init_store(root)
    issue, _ = rust_beads.create(
        root / "sdd/beads",
        title="Noted",
        issue_type=IssueType.PLAN,
        now="2026-01-01T00:00:00Z",
    )

    noted, outcome = rust_beads.append_note(
        root / "sdd/beads",
        issue.id,
        "done",
        author="agent-1",
        now="2026-01-01T00:01:00Z",
    )

    assert outcome["operation"] == "note"
    assert outcome["issue_ids"] == [issue.id]
    assert noted.notes_text == "[2026-01-01T00:01:00Z · agent-1] done"
    # Projection-off: mutations no longer rewrite issues.jsonl; export it
    # explicitly before asserting on projected content.
    rust_beads.export_jsonl(root / "sdd/beads")
    projection = json.loads(
        (root / "sdd/beads/issues.jsonl").read_text(encoding="utf-8")
    )
    assert projection["notes"][0]["id"].startswith(
        "gold-1:000002:note_appended:gold-1:"
    )
    assert projection["notes"][0] | {"id": ""} == {
        "id": "",
        "timestamp": "2026-01-01T00:01:00Z",
        "author": "agent-1",
        "text": "done",
    }


def test_set_link_projections_batch_is_authorized_and_returns_aggregate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    init_store(root)
    issue, _ = rust_beads.create(
        root / "sdd/beads",
        title="Linked",
        issue_type=IssueType.PLAN,
        now="2026-01-01T00:00:00Z",
    )

    outcome = rust_beads.set_link_projections(
        root / "sdd/beads",
        [
            {
                "issue_id": issue.id,
                "target_ref": "plan:202609/a.md",
                "relation": "related",
                "direction": "out",
                "present": True,
                "operation_id": "a" * 32,
                "description": "present edge",
                "origin": "manual",
                "uses": 1,
                "now": "2026-01-01T00:01:00Z",
            },
            {
                "issue_id": issue.id,
                "target_ref": "plan:202609/a.md",
                "relation": "related",
                "direction": "out",
                "present": False,
                "operation_id": "b" * 32,
                "now": "2026-01-01T00:02:00Z",
            },
        ],
    )

    assert outcome["operation"] == "link_project"
    assert outcome["changed"] is True
    assert outcome["issue_ids"] == [issue.id]
    replay = rust_beads.set_link_projections(
        root / "sdd/beads",
        [
            {
                "issue_id": issue.id,
                "target_ref": "plan:202609/a.md",
                "relation": "related",
                "direction": "out",
                "present": False,
                "operation_id": "b" * 32,
                "now": "2026-01-01T00:02:00Z",
            }
        ],
    )
    assert replay["changed"] is False


def test_set_link_projections_refuses_unsandboxed_pytest_store_before_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsafe_beads_dir = tmp_path / "production" / "sdd/beads"
    unsafe_beads_dir.mkdir(parents=True)
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    def fail_binding(_name: str):
        raise AssertionError("unsafe bead write reached Rust binding")

    monkeypatch.setattr(rust_beads, "require_rust_binding", fail_binding)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "mutation facade write guard")
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(sandbox))

    with pytest.raises(RuntimeError) as exc_info:
        rust_beads.set_link_projections(unsafe_beads_dir, [])

    message = str(exc_info.value)
    assert "set_link_projections" in message
    assert str(unsafe_beads_dir.resolve()) in message


def test_mutation_facade_refuses_unsandboxed_pytest_store_before_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unsafe_beads_dir = tmp_path / "production" / "sdd/beads"
    unsafe_beads_dir.mkdir(parents=True)
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    def fail_binding(_name: str):
        raise AssertionError("unsafe bead write reached Rust binding")

    monkeypatch.setattr(rust_beads, "require_rust_binding", fail_binding)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "mutation facade write guard")
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(sandbox))

    with pytest.raises(RuntimeError) as exc_info:
        rust_beads.create(
            unsafe_beads_dir,
            title="Unsafe",
            issue_type=IssueType.PLAN,
        )

    message = str(exc_info.value)
    assert "create" in message
    assert str(unsafe_beads_dir.resolve()) in message
    assert str(sandbox.resolve()) in message


def test_mutation_facade_writes_events_and_repairs_jsonl_projection(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    init_store(root)
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
    rust_beads.update(
        root / "sdd/beads",
        child.id,
        status="in_progress",
        assignee="agent",
        now="2026-01-01T00:02:00Z",
    )

    stream_path = root / f"sdd/beads/events/streams/{epic.id}.jsonl"
    operations = [
        json.loads(line)["operation"]
        for line in stream_path.read_text().splitlines()
        if line.strip()
    ]
    assert operations == ["issue_created", "issue_created", "issue_updated"]

    projection_path = root / "sdd/beads/issues.jsonl"
    projection_path.write_text("")
    rust_beads.export_jsonl(root / "sdd/beads")
    projection = projection_path.read_text()
    assert f'"id":"{epic.id}"' in projection
    assert f'"id":"{child.id}"' in projection
    assert '"assignee":"agent"' in projection


def _assert_jsonl_equal(left_root: Path, right_root: Path) -> None:
    assert (left_root / "sdd/beads" / "issues.jsonl").read_text() == (
        right_root / "sdd/beads" / "issues.jsonl"
    ).read_text()
