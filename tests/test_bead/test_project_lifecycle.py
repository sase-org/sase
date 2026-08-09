"""Tests for BeadProject lifecycle mutations."""

from __future__ import annotations

import pytest

from sase.bead.model import IssueType, Resolution, Status
from sase.bead.project import AlreadyReadyError, NotAPlanError


def test_close_single(project):
    epic = project.create("Epic", IssueType.PLAN)
    closed = project.close([epic.id])
    assert len(closed) == 1
    assert closed[0].status == Status.CLOSED


def test_close_multiple(project):
    e1 = project.create("E1", IssueType.PLAN)
    e2 = project.create("E2", IssueType.PLAN)
    closed = project.close([e1.id, e2.id])
    assert len(closed) == 2
    assert all(i.status == Status.CLOSED for i in closed)


def test_close_with_reason(project):
    epic = project.create("Epic", IssueType.PLAN)
    closed = project.close([epic.id], reason="done")
    assert closed[0].close_reason == "done"


def test_close_with_resolution(project):
    epic = project.create("Epic", IssueType.PLAN)
    closed = project.close(
        [epic.id],
        reason="No longer needed",
        resolution="canceled",
    )
    assert closed[0].resolution is Resolution.CANCELED
    assert project.show(epic.id).resolution is Resolution.CANCELED


def test_close_plan_rejects_open_children(project):
    epic = project.create("Epic", IssueType.PLAN)
    c1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    c2 = project.create("C2", IssueType.PHASE, parent_id=epic.id)
    with pytest.raises(ValueError, match="descendant\\(s\\) are not closed"):
        project.close([epic.id])
    for issue_id in [c1.id, c2.id, epic.id]:
        assert project.show(issue_id).status == Status.OPEN


def test_close_plan_skips_already_closed_children(project):
    epic = project.create("Epic", IssueType.PLAN)
    c1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    c2 = project.create("C2", IssueType.PHASE, parent_id=epic.id)
    # Close c1 first
    project.close([c1.id])
    with pytest.raises(ValueError, match="descendant\\(s\\) are not closed"):
        project.close([epic.id])
    project.close([c2.id])
    # Once every child was closed deliberately, the plan can close normally.
    closed = project.close([epic.id])
    closed_ids = [i.id for i in closed]
    assert c1.id not in closed_ids
    assert c2.id not in closed_ids
    assert closed_ids == [epic.id]


def test_force_close_plan_records_parent_in_child_reason(project):
    epic = project.create("Epic", IssueType.PLAN)
    c1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    project.close(
        [epic.id],
        reason="No longer needed",
        resolution="canceled",
        force=True,
    )
    swept = project.show(c1.id)
    assert swept.close_reason == f"forced by {epic.id}: No longer needed"
    assert swept.resolution is Resolution.CANCELED


def test_force_close_requires_reason_and_non_done_resolution(project):
    epic = project.create("Epic", IssueType.PLAN)
    with pytest.raises(ValueError, match="requires a non-empty --reason"):
        project.close([epic.id], resolution="canceled", force=True)
    with pytest.raises(ValueError, match="'done' is not allowed"):
        project.close([epic.id], reason="Finished", force=True)


def test_close_not_found(project):
    with pytest.raises(KeyError):
        project.close(["nonexistent"])


def test_remove_plan(project):
    epic = project.create("Epic", IssueType.PLAN)
    removed = project.remove(epic.id)
    assert len(removed) == 1
    assert removed[0].id == epic.id
    with pytest.raises(KeyError):
        project.show(epic.id)


def test_remove_plan_cascades_children(project):
    epic = project.create("Epic", IssueType.PLAN)
    c1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    c2 = project.create("C2", IssueType.PHASE, parent_id=epic.id)
    removed = project.remove(epic.id)
    removed_ids = [i.id for i in removed]
    assert c1.id in removed_ids
    assert c2.id in removed_ids
    assert epic.id in removed_ids
    assert project.list_issues() == []


def test_remove_many_deduplicates_overlapping_and_repeated_requests(project):
    epic = project.create("Epic", IssueType.PLAN)
    child = project.create("Child", IssueType.PHASE, parent_id=epic.id)
    independent = project.create("Independent", IssueType.PLAN)

    removed = project.remove_many([epic.id, child.id, independent.id, independent.id])

    assert [issue.id for issue in removed] == [
        child.id,
        epic.id,
        independent.id,
    ]
    assert project.list_issues() == []


def test_remove_many_missing_id_is_atomic(project):
    epic = project.create("Epic", IssueType.PLAN)
    child = project.create("Child", IssueType.PHASE, parent_id=epic.id)
    survivor = project.create("Survivor", IssueType.PLAN)
    project.add_dependency(survivor.id, child.id)
    projection_before = (project.beads_dir / "issues.jsonl").read_bytes()
    rows_before = project._conn.execute("SELECT id FROM issues ORDER BY id").fetchall()

    with pytest.raises(KeyError, match="Issue not found: missing"):
        project.remove_many([epic.id, "missing"])

    assert (project.beads_dir / "issues.jsonl").read_bytes() == projection_before
    assert project._conn.execute("SELECT id FROM issues ORDER BY id").fetchall() == (
        rows_before
    )
    assert project.show(epic.id).id == epic.id
    assert project.show(child.id).id == child.id
    assert project.show(survivor.id).dependencies[0].depends_on_id == child.id


def test_remove_phase(project):
    epic = project.create("Epic", IssueType.PLAN)
    child = project.create("Child", IssueType.PHASE, parent_id=epic.id)
    removed = project.remove(child.id)
    assert len(removed) == 1
    assert removed[0].id == child.id
    # Parent still exists
    assert project.show(epic.id).id == epic.id


def test_remove_not_found(project):
    with pytest.raises(KeyError):
        project.remove("nonexistent")


def test_remove_updates_jsonl(project):
    epic = project.create("Epic", IssueType.PLAN)
    project.remove(epic.id)
    jsonl = (project.beads_dir / "issues.jsonl").read_text()
    assert jsonl.strip() == ""


def test_create_defaults_is_ready_to_work_false(project):
    epic = project.create("Epic", IssueType.PLAN)
    assert project.show(epic.id).is_ready_to_work is False


def test_mark_ready_to_work_flips_flag(project):
    epic = project.create("Epic", IssueType.PLAN)
    updated = project.mark_ready_to_work(epic.id)
    assert updated.is_ready_to_work is True
    assert project.show(epic.id).is_ready_to_work is True


def test_mark_ready_to_work_rejects_phase(project):
    epic = project.create("Epic", IssueType.PLAN)
    child = project.create("Child", IssueType.PHASE, parent_id=epic.id)
    with pytest.raises(NotAPlanError):
        project.mark_ready_to_work(child.id)


def test_mark_ready_to_work_idempotency_raises(project):
    epic = project.create("Epic", IssueType.PLAN)
    project.mark_ready_to_work(epic.id)
    with pytest.raises(AlreadyReadyError):
        project.mark_ready_to_work(epic.id)


def test_mark_ready_to_work_unknown_id(project):
    with pytest.raises(KeyError):
        project.mark_ready_to_work("nonexistent")


def test_update_rejects_is_ready_to_work(project):
    epic = project.create("Epic", IssueType.PLAN)
    with pytest.raises(ValueError):
        project.update(epic.id, is_ready_to_work=True)
    # Flag is unchanged.
    assert project.show(epic.id).is_ready_to_work is False


def test_mark_ready_to_work_persists_to_jsonl(project):
    epic = project.create("Epic", IssueType.PLAN)
    project.mark_ready_to_work(epic.id)
    jsonl = (project.beads_dir / "issues.jsonl").read_text()
    assert '"is_ready_to_work":true' in jsonl
