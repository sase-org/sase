"""Tests for sase.bead.project (BeadProject API)."""

from __future__ import annotations

import pytest

from sase.bead.model import BeadTier, IssueType, PhaseSize, Status


def test_create_epic(project):
    issue = project.create("My Epic", IssueType.PLAN)
    assert issue.title == "My Epic"
    assert issue.issue_type == IssueType.PLAN
    assert issue.tier == BeadTier.EPIC
    assert issue.status == Status.OPEN
    assert issue.id  # has an ID


def test_create_plan_and_filter_by_tier(project):
    plan = project.create("Plan", IssueType.PLAN, tier=BeadTier.PLAN)
    epic = project.create("Epic", IssueType.PLAN)

    plans = project.list_issues(tiers=[BeadTier.PLAN])

    assert [issue.id for issue in plans] == [plan.id]
    assert project.show(epic.id).tier == BeadTier.EPIC


def test_create_records_explicit_created_by(project):
    issue = project.create(
        "Attributed task",
        IssueType.TASK,
        task_type="bug",
        size="small",
        created_by="bbugyi200.athena.q8--plan",
    )
    assert issue.created_by == "bbugyi200.athena.q8--plan"
    assert project.show(issue.id).created_by == "bbugyi200.athena.q8--plan"


def test_create_without_created_by_falls_back_to_owner(project):
    issue = project.create(
        "Unattributed task", IssueType.TASK, task_type="bug", size="small"
    )
    assert issue.created_by == issue.owner


def test_create_phase_inherits_created_by_from_parent(project):
    epic = project.create(
        "Epic",
        IssueType.PLAN,
        created_by="bbugyi200.athena.q8--plan",
    )
    phase = project.create("Phase", IssueType.PHASE, parent_id=epic.id)
    assert phase.created_by == "bbugyi200.athena.q8--plan"


def test_create_and_update_model(project):
    epic = project.create("Epic", IssueType.PLAN, model="claude/opus")
    assert epic.model == "claude/opus"
    assert project.show(epic.id).model == "claude/opus"

    cleared = project.update(epic.id, model="")
    assert cleared.model == ""

    relabeled = project.update(epic.id, model="codex/gpt-5.5")
    assert relabeled.model == "codex/gpt-5.5"
    assert project.show(epic.id).model == "codex/gpt-5.5"


def test_create_and_update_phase_size(project):
    epic = project.create("Epic", IssueType.PLAN)
    phase = project.create(
        "Phase",
        IssueType.PHASE,
        parent_id=epic.id,
        size=PhaseSize.XSMALL,
    )
    assert phase.size is PhaseSize.XSMALL
    assert project.show(phase.id).size is PhaseSize.XSMALL

    updated = project.update(phase.id, size="xlarge")
    assert updated.size is PhaseSize.XLARGE
    assert project.show(phase.id).size is PhaseSize.XLARGE


def test_create_epic_with_patch_metadata(project):
    issue = project.create(
        "My Epic",
        IssueType.PLAN,
        changespec_name="feature_epic",
        changespec_bug_id=12345,
    )
    assert issue.changespec_name == "feature_epic"
    assert issue.changespec_bug_id == "12345"
    assert project.show(issue.id).changespec_name == "feature_epic"


def test_create_epic_with_patch_metadata_aliases(project):
    issue = project.create(
        "My Epic",
        IssueType.PLAN,
        patch_name="feature_epic",
        patch_bug_id=12345,
    )
    assert issue.patch_name == "feature_epic"
    assert issue.patch_bug_id == "12345"
    assert project.show(issue.id).changespec_name == "feature_epic"


def test_create_child(project):
    epic = project.create("Epic", IssueType.PLAN)
    child = project.create("Child", IssueType.PHASE, parent_id=epic.id)
    assert child.parent_id == epic.id
    assert child.issue_type == IssueType.PHASE


def test_create_child_rejects_patch_metadata(project):
    epic = project.create("Epic", IssueType.PLAN)
    with pytest.raises(ValueError, match="Only plan issues can carry"):
        project.create(
            "Child",
            IssueType.PHASE,
            parent_id=epic.id,
            changespec_name="feature_epic",
        )


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
    first = project.create("First", IssueType.TASK, task_type="bug", size="small")
    second = project.create("Second", IssueType.TASK, task_type="bug", size="small")
    project.update(first.id, status="ready")
    project.update(second.id, status="ready")
    project.add_dependency(second.id, first.id)

    ready = project.ready()
    ready_ids = [i.id for i in ready]
    assert first.id in ready_ids
    assert second.id not in ready_ids


def test_update(project):
    epic = project.create("Original", IssueType.PLAN)
    updated = project.update(epic.id, title="Updated")
    assert updated.title == "Updated"


def test_update_patch_metadata(project):
    epic = project.create("Epic", IssueType.PLAN)
    updated = project.update(
        epic.id,
        changespec_name="feature_epic",
        changespec_bug_id=12345,
    )
    assert updated.changespec_name == "feature_epic"
    assert updated.changespec_bug_id == "12345"


def test_update_patch_metadata_aliases(project):
    epic = project.create("Epic", IssueType.PLAN)
    updated = project.update(
        epic.id,
        patch_name="feature_epic",
        patch_bug_id=12345,
    )
    assert updated.patch_name == "feature_epic"
    assert updated.patch_bug_id == "12345"


def test_update_rejects_bug_id_without_patch(project):
    epic = project.create("Epic", IssueType.PLAN)
    with pytest.raises(ValueError, match="requires changespec_name"):
        project.update(epic.id, changespec_bug_id="12345")


def test_update_status(project):
    epic = project.create("Epic", IssueType.PLAN)
    updated = project.update(epic.id, status="in_progress")
    assert updated.status == Status.IN_PROGRESS


def test_update_not_found(project):
    with pytest.raises(KeyError):
        project.update("nonexistent", title="X")


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
    child = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    project.close([child.id])
    project.close([epic.id])

    s = project.stats()
    assert s["total"] == 2
    assert s.get("closed", 0) == 2
    assert s.get("open", 0) == 0
    assert s.get("plan", 0) == 1
    assert s.get("phase", 0) == 1


def test_get_epic_children(project):
    epic = project.create("Epic", IssueType.PLAN)
    c1 = project.create("C1", IssueType.PHASE, parent_id=epic.id)
    c2 = project.create("C2", IssueType.PHASE, parent_id=epic.id)

    children = project.get_epic_children(epic.id)
    child_ids = [c.id for c in children]
    assert c1.id in child_ids
    assert c2.id in child_ids
