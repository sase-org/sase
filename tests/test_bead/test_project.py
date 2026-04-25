"""Tests for sase.bead.project (BeadProject API)."""

from __future__ import annotations

import pytest

from sase.bead.model import IssueType, Status
from sase.bead.project import AlreadyReadyError, BeadProject, NotAPlanError


@pytest.fixture
def project(tmp_path):
    """Create a fresh BeadProject in a temp directory."""
    with BeadProject.init(tmp_path) as proj:
        yield proj


def test_init_creates_beads_dir(tmp_path):
    with BeadProject.init(tmp_path):
        assert (tmp_path / ".sase_beads").is_dir()
        assert (tmp_path / ".sase_beads" / "config.json").exists()
        assert (tmp_path / ".sase_beads" / "beads.db").exists()
        assert (tmp_path / ".sase_beads" / "issues.jsonl").exists()


def test_init_already_exists(tmp_path):
    with BeadProject.init(tmp_path):
        pass
    # Second init should succeed without error
    with BeadProject.init(tmp_path) as proj:
        assert proj is not None


def test_constructor_raises_without_beads_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        BeadProject(tmp_path)


def test_create_epic(project):
    issue = project.create("My Epic", IssueType.PLAN)
    assert issue.title == "My Epic"
    assert issue.issue_type == IssueType.PLAN
    assert issue.status == Status.OPEN
    assert issue.id  # has an ID


def test_create_child(project):
    epic = project.create("Epic", IssueType.PLAN)
    child = project.create("Child", IssueType.PHASE, parent_id=epic.id)
    assert child.parent_id == epic.id
    assert child.issue_type == IssueType.PHASE


def test_show(project):
    epic = project.create("Show Test", IssueType.PLAN)
    found = project.show(epic.id)
    assert found.title == "Show Test"


def test_show_not_found(project):
    with pytest.raises(KeyError):
        project.show("nonexistent")


def test_list_all(project):
    project.create("E1", IssueType.PLAN)
    project.create("E2", IssueType.PLAN)
    issues = project.list_issues()
    assert len(issues) == 2


def test_list_filter_status(project):
    epic = project.create("E1", IssueType.PLAN)
    project.create("E2", IssueType.PLAN)
    project.close([epic.id])
    open_issues = project.list_issues(statuses=[Status.OPEN])
    assert len(open_issues) == 1


def test_list_filter_type(project):
    epic = project.create("Epic", IssueType.PLAN)
    project.create("Child", IssueType.PHASE, parent_id=epic.id)
    epics = project.list_issues(issue_types=[IssueType.PLAN])
    assert len(epics) == 1
    assert epics[0].issue_type == IssueType.PLAN


def test_ready(project):
    epic = project.create("Epic", IssueType.PLAN)
    child1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    child2 = project.create("C2", IssueType.PHASE, parent_id=epic.id)
    project.add_dependency(child2.id, child1.id)

    ready = project.ready()
    ready_ids = [i.id for i in ready]
    assert epic.id in ready_ids
    assert child1.id in ready_ids
    assert child2.id not in ready_ids  # blocked by child1


def test_update(project):
    epic = project.create("Original", IssueType.PLAN)
    updated = project.update(epic.id, title="Updated")
    assert updated.title == "Updated"


def test_update_status(project):
    epic = project.create("Epic", IssueType.PLAN)
    updated = project.update(epic.id, status="in_progress")
    assert updated.status == Status.IN_PROGRESS


def test_update_not_found(project):
    with pytest.raises(KeyError):
        project.update("nonexistent", title="X")


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


def test_close_plan_cascades_children(project):
    epic = project.create("Epic", IssueType.PLAN)
    c1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    c2 = project.create("C2", IssueType.PHASE, parent_id=epic.id)
    closed = project.close([epic.id])
    closed_ids = [i.id for i in closed]
    assert c1.id in closed_ids
    assert c2.id in closed_ids
    assert epic.id in closed_ids
    # All should now be closed
    for issue_id in [c1.id, c2.id, epic.id]:
        assert project.show(issue_id).status == Status.CLOSED


def test_close_plan_skips_already_closed_children(project):
    epic = project.create("Epic", IssueType.PLAN)
    c1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    project.create("C2", IssueType.PHASE, parent_id=epic.id)
    # Close c1 first
    project.close([c1.id])
    # Now close the plan — c1 should not appear again
    closed = project.close([epic.id])
    closed_ids = [i.id for i in closed]
    assert c1.id not in closed_ids


def test_close_plan_cascades_reason_to_children(project):
    epic = project.create("Epic", IssueType.PLAN)
    c1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    project.close([epic.id], reason="completed")
    assert project.show(c1.id).close_reason == "completed"


def test_close_not_found(project):
    with pytest.raises(KeyError):
        project.close(["nonexistent"])


def test_add_dependency(project):
    epic = project.create("Epic", IssueType.PLAN)
    c1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    c2 = project.create("C2", IssueType.PHASE, parent_id=epic.id)
    dep = project.add_dependency(c2.id, c1.id)
    assert dep.issue_id == c2.id
    assert dep.depends_on_id == c1.id


def test_blocked(project):
    epic = project.create("Epic", IssueType.PLAN)
    c1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    c2 = project.create("C2", IssueType.PHASE, parent_id=epic.id)
    project.add_dependency(c2.id, c1.id)

    blocked = project.blocked()
    blocked_ids = [i.id for i in blocked]
    assert c2.id in blocked_ids
    assert c1.id not in blocked_ids


def test_stats(project):
    epic = project.create("Epic", IssueType.PLAN)
    project.create("C1", IssueType.PHASE, parent_id=epic.id)
    project.close([epic.id])

    s = project.stats()
    assert s["total"] == 2
    assert s.get("closed", 0) == 2
    assert s.get("open", 0) == 0
    assert s.get("plan", 0) == 1
    assert s.get("phase", 0) == 1


def test_doctor_clean(project):
    messages = project.doctor()
    assert any("OK" in m for m in messages)


def test_doctor_detects_orphan(project):
    """Create a child whose parent doesn't exist (via direct db manipulation)."""
    # Create a parent first to satisfy the constraint, then delete it
    epic = project.create("Epic", IssueType.PLAN)
    project.create("Child", IssueType.PHASE, parent_id=epic.id)

    # Disable FK constraints temporarily so cascade doesn't remove child
    project._conn.execute("PRAGMA foreign_keys=OFF")
    project._conn.execute("DELETE FROM issues WHERE id = ?", (epic.id,))
    project._conn.commit()
    project._conn.execute("PRAGMA foreign_keys=ON")

    messages = project.doctor()
    assert any("orphan" in m.lower() for m in messages)


def test_get_epic_children(project):
    epic = project.create("Epic", IssueType.PLAN)
    c1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    c2 = project.create("C2", IssueType.PHASE, parent_id=epic.id)

    children = project.get_epic_children(epic.id)
    child_ids = [c.id for c in children]
    assert c1.id in child_ids
    assert c2.id in child_ids


def test_jsonl_persisted_after_create(project):
    project.create("Epic", IssueType.PLAN)
    jsonl = (project.beads_dir / "issues.jsonl").read_text()
    assert "Epic" in jsonl


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


def test_counter_persists_across_instances(tmp_path):
    with BeadProject.init(tmp_path) as proj1:
        proj1.create("E1", IssueType.PLAN)
        proj1.create("E2", IssueType.PLAN)

    # Open a new instance
    with BeadProject(tmp_path) as proj2:
        proj2.create("E3", IssueType.PLAN)
        # Should not reuse IDs
        all_ids = [i.id for i in proj2.list_issues()]
        assert len(all_ids) == len(set(all_ids))
