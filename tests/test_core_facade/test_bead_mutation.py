"""Parity tests for the Rust bead mutation facade."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.bead.config import save_config
from sase.bead.model import BeadTier, IssueType, Status
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
    _init_store(root)
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


def test_append_note_facade_returns_issue_and_repairs_projection(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    _init_store(root)
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
    assert noted.notes == "[2026-01-01T00:01:00Z · agent-1] done"
    projection = (root / "sdd/beads/issues.jsonl").read_text(encoding="utf-8")
    assert "[2026-01-01T00:01:00Z · agent-1] done" in projection


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


def test_claim_for_agent_launch_converts_issue_and_reassigns(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    _init_store(root)
    epic, _ = rust_beads.create(
        root / "sdd/beads",
        title="Epic",
        issue_type=IssueType.PLAN,
        now="2026-01-01T00:00:00Z",
    )
    phase, _ = rust_beads.create(
        root / "sdd/beads",
        title="Phase",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        now="2026-01-01T00:01:00Z",
    )

    claimed, outcome = rust_beads.claim_for_agent_launch(
        root / "sdd/beads",
        phase.id,
        "agent-1",
        now="2026-01-01T00:02:00Z",
    )

    assert outcome["operation"] == "claim_for_agent_launch"
    assert outcome["changed"] is True
    assert outcome["issue_ids"] == [phase.id]
    assert claimed.id == phase.id
    assert claimed.status == Status.IN_PROGRESS
    assert claimed.assignee == "agent-1"
    assert claimed.updated_at == "2026-01-01T00:02:00Z"

    reassigned, _ = rust_beads.claim_for_agent_launch(
        root / "sdd/beads",
        phase.id,
        "agent-2",
        now="2026-01-01T00:03:00Z",
    )
    assert reassigned.status == Status.IN_PROGRESS
    assert reassigned.assignee == "agent-2"
    assert reassigned.updated_at == "2026-01-01T00:03:00Z"


def test_preclaim_epic_work_converts_batch_and_returns_prior_state(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    _init_store(root)
    epic, _ = rust_beads.create(
        root / "sdd/beads",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        now="2026-01-01T00:00:00Z",
    )
    first, _ = rust_beads.create(
        root / "sdd/beads",
        title="First",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        now="2026-01-01T00:01:00Z",
    )
    second, _ = rust_beads.create(
        root / "sdd/beads",
        title="Second",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        now="2026-01-01T00:02:00Z",
    )
    rust_beads.update(
        root / "sdd/beads",
        second.id,
        status="in_progress",
        assignee="old-worker",
        now="2026-01-01T00:03:00Z",
    )

    assigned, outcome = rust_beads.preclaim_epic_work(
        root / "sdd/beads",
        epic.id,
        [(first.id, "epic.1"), (second.id, "epic.2")],
        land_agent_name="epic.land",
        now="2026-01-01T00:04:00Z",
    )

    assert [(issue.id, issue.status, issue.assignee) for issue in assigned] == [
        (first.id, Status.IN_PROGRESS, "epic.1"),
        (second.id, Status.IN_PROGRESS, "epic.2"),
        (epic.id, Status.IN_PROGRESS, "epic.land"),
    ]
    assert outcome["operation"] == "preclaim_epic_work"
    assert outcome["rollback_preclaims"] == [
        {"bead_id": first.id, "status": "open", "assignee": ""},
        {
            "bead_id": second.id,
            "status": "in_progress",
            "assignee": "old-worker",
        },
        {"bead_id": epic.id, "status": "open", "assignee": ""},
    ]


def test_preclaim_epic_work_allows_empty_subset_without_land_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    _init_store(root)
    epic, _ = rust_beads.create(
        root / "sdd/beads",
        title="Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        now="2026-01-01T00:00:00Z",
    )
    phase, _ = rust_beads.create(
        root / "sdd/beads",
        title="Phase",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        now="2026-01-01T00:01:00Z",
    )

    assigned, outcome = rust_beads.preclaim_epic_work(
        root / "sdd/beads",
        epic.id,
        [],
        land_agent_name=None,
        now="2026-01-01T00:02:00Z",
    )

    assert assigned == []
    assert outcome["operation"] == "preclaim_epic_work"
    assert outcome["rollback_preclaims"] == []
    with BeadProject(root) as project:
        assert project.show(epic.id).status is Status.OPEN
        assert project.show(epic.id).assignee == ""
        assert project.show(phase.id).status is Status.OPEN
        assert project.show(phase.id).assignee == ""


def test_claim_for_agent_launch_maps_missing_and_preserves_specific_failures(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rust"
    _init_store(root)
    epic, _ = rust_beads.create(
        root / "sdd/beads",
        title="Epic",
        issue_type=IssueType.PLAN,
        now="2026-01-01T00:00:00Z",
    )
    rust_beads.close(
        root / "sdd/beads",
        [epic.id],
        now="2026-01-01T00:01:00Z",
    )

    with pytest.raises(KeyError, match="Issue not found: missing"):
        rust_beads.claim_for_agent_launch(root / "sdd/beads", "missing", "agent")
    with pytest.raises(ValueError, match="closed: cannot claim closed bead"):
        rust_beads.claim_for_agent_launch(root / "sdd/beads", epic.id, "agent")
    with pytest.raises(ValueError, match="validation: agent name"):
        rust_beads.claim_for_agent_launch(root / "sdd/beads", epic.id, "  ")


def test_wait_claim_facade_claims_idempotently_and_releases(tmp_path: Path) -> None:
    root = tmp_path / "rust"
    _init_store(root)
    epic, _ = rust_beads.create(
        root / "sdd/beads",
        title="Epic",
        issue_type=IssueType.PLAN,
        now="2026-01-01T00:00:00Z",
    )
    phase, _ = rust_beads.create(
        root / "sdd/beads",
        title="Phase",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        now="2026-01-01T00:00:01Z",
    )

    claimed, claim_outcome = rust_beads.claim_for_agent_wait(
        root / "sdd/beads",
        phase.id,
        "agent-1",
        now="2026-01-01T00:01:00Z",
    )
    retained, retained_outcome = rust_beads.claim_for_agent_wait(
        root / "sdd/beads",
        phase.id,
        "agent-1",
        now="2026-01-01T00:02:00Z",
    )
    released, release_outcome = rust_beads.release_agent_claim(
        root / "sdd/beads",
        phase.id,
        "agent-1",
        now="2026-01-01T00:03:00Z",
    )

    assert (claimed.status, claimed.assignee) == (Status.CLAIMED, "agent-1")
    assert claim_outcome["changed"] is True
    assert (retained.status, retained.assignee) == (Status.CLAIMED, "agent-1")
    assert retained_outcome["changed"] is False
    assert (released.status, released.assignee) == (Status.OPEN, "")
    assert release_outcome["changed"] is True


def test_mutation_facade_writes_events_and_repairs_jsonl_projection(
    tmp_path: Path,
) -> None:
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
