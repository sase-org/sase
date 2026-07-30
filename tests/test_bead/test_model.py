"""Tests for issue and dependency models."""

import pytest

from sase.bead.model import (
    BeadTier,
    Dependency,
    Issue,
    IssueType,
    PhaseSize,
    Resolution,
    Status,
)


class TestIssueValidation:
    def test_valid_phase_with_parent(self) -> None:
        issue = Issue(
            id="test-1",
            title="A phase",
            issue_type=IssueType.PHASE,
            parent_id="test-0",
        )
        issue.validate()  # Should not raise

    def test_phase_without_parent_raises(self) -> None:
        issue = Issue(
            id="test-1",
            title="A phase",
            issue_type=IssueType.PHASE,
            parent_id=None,
        )
        with pytest.raises(ValueError, match="Phase issues must have a parent_id"):
            issue.validate()

    def test_valid_plan_without_parent(self) -> None:
        issue = Issue(
            id="test-1",
            title="A plan",
            issue_type=IssueType.PLAN,
            parent_id=None,
        )
        issue.validate()  # Should not raise

    def test_plan_with_parent_is_valid(self) -> None:
        issue = Issue(
            id="test-1",
            title="A sub-plan",
            issue_type=IssueType.PLAN,
            parent_id="test-0",
        )
        issue.validate()  # Should not raise (plans can have parents)

    def test_default_status_is_open(self) -> None:
        issue = Issue(id="test-1", title="Test")
        assert issue.status == Status.OPEN

    def test_default_type_is_phase(self) -> None:
        issue = Issue(id="test-1", title="Test")
        assert issue.issue_type == IssueType.PHASE

    def test_default_is_ready_to_work_false(self) -> None:
        issue = Issue(id="test-1", title="Test")
        assert issue.is_ready_to_work is False

    def test_default_model_empty(self) -> None:
        issue = Issue(id="test-1", title="Test")
        assert issue.model == ""

    def test_default_refs_empty(self) -> None:
        issue = Issue(id="test-1", title="Test")
        assert issue.refs == []

    def test_default_size_none(self) -> None:
        issue = Issue(id="test-1", title="Test")
        assert issue.size is None

    def test_phase_size_assignment(self) -> None:
        issue = Issue(
            id="test-1",
            title="Test",
            issue_type=IssueType.PHASE,
            parent_id="test-0",
            size=PhaseSize.LARGE,
        )
        assert issue.size == PhaseSize.LARGE
        issue.validate()

    def test_plan_with_phase_size_raises(self) -> None:
        issue = Issue(
            id="test-1",
            title="Test",
            issue_type=IssueType.PLAN,
            size=PhaseSize.SMALL,
        )
        with pytest.raises(ValueError, match="Only phase and task issues"):
            issue.validate()

    def test_task_can_have_size_without_parent(self) -> None:
        issue = Issue(
            id="test-task",
            title="A task",
            issue_type=IssueType.TASK,
            size=PhaseSize.MEDIUM,
        )

        issue.validate()

    def test_task_with_parent_raises(self) -> None:
        issue = Issue(
            id="test-task",
            title="A nested task",
            issue_type=IssueType.TASK,
            parent_id="test-0",
        )

        with pytest.raises(ValueError, match="Task issues cannot have a parent_id"):
            issue.validate()

    def test_task_with_tier_raises(self) -> None:
        issue = Issue(
            id="test-task",
            title="A tiered task",
            issue_type=IssueType.TASK,
            tier=BeadTier.EPIC,
        )

        with pytest.raises(ValueError, match="Task issues cannot carry"):
            issue.validate()

    def test_model_assignment(self) -> None:
        issue = Issue(
            id="test-1",
            title="Test",
            issue_type=IssueType.PLAN,
            model="codex/gpt-5.5",
        )
        assert issue.model == "codex/gpt-5.5"
        issue.validate()

    def test_refs_assignment(self) -> None:
        issue = Issue(
            id="test-1",
            title="Test",
            issue_type=IssueType.PLAN,
            refs=["research:202607/report.md", "bead:sase-bb.1"],
        )
        assert issue.refs == [
            "research:202607/report.md",
            "bead:sase-bb.1",
        ]

    def test_phase_with_is_ready_to_work_raises(self) -> None:
        issue = Issue(
            id="test-1",
            title="A phase",
            issue_type=IssueType.PHASE,
            parent_id="test-0",
            is_ready_to_work=True,
        )
        with pytest.raises(ValueError, match="Only plan issues"):
            issue.validate()

    def test_plan_with_is_ready_to_work_is_valid(self) -> None:
        issue = Issue(
            id="test-1",
            title="A plan",
            issue_type=IssueType.PLAN,
            is_ready_to_work=True,
        )
        issue.validate()  # Should not raise

    def test_phase_with_tier_raises(self) -> None:
        issue = Issue(
            id="test-1",
            title="A phase",
            issue_type=IssueType.PHASE,
            tier=BeadTier.EPIC,
            parent_id="test-0",
        )
        with pytest.raises(ValueError, match="Phase issues cannot carry"):
            issue.validate()

    def test_task_with_changespec_metadata_raises(self) -> None:
        issue = Issue(
            id="test-task",
            title="A task",
            issue_type=IssueType.TASK,
            changespec_name="feature_epic",
        )

        with pytest.raises(ValueError, match="Only plan issues can carry"):
            issue.validate()

    def test_task_with_is_ready_to_work_raises(self) -> None:
        issue = Issue(
            id="test-task",
            title="A task",
            issue_type=IssueType.TASK,
            is_ready_to_work=True,
        )

        with pytest.raises(ValueError, match="Only plan issues"):
            issue.validate()

    def test_ready_status_requires_task_type(self) -> None:
        issue = Issue(
            id="test-1",
            title="A plan",
            issue_type=IssueType.PLAN,
            status=Status.READY,
        )

        with pytest.raises(ValueError, match="Only task issues can have ready status"):
            issue.validate()

        issue.issue_type = IssueType.TASK
        issue.validate()

    def test_plan_with_changespec_name_is_valid(self) -> None:
        issue = Issue(
            id="test-1",
            title="A plan",
            issue_type=IssueType.PLAN,
            changespec_name="feature_epic",
        )
        issue.validate()

    def test_plan_with_changespec_bug_id_is_valid(self) -> None:
        issue = Issue(
            id="test-1",
            title="A plan",
            issue_type=IssueType.PLAN,
            changespec_name="feature_epic",
            changespec_bug_id="12345",
        )
        issue.validate()

    def test_phase_with_changespec_metadata_raises(self) -> None:
        issue = Issue(
            id="test-1",
            title="A phase",
            issue_type=IssueType.PHASE,
            parent_id="test-0",
            changespec_name="feature_epic",
        )
        with pytest.raises(ValueError, match="Only plan issues can carry"):
            issue.validate()

    def test_bug_id_without_changespec_name_raises(self) -> None:
        issue = Issue(
            id="test-1",
            title="A plan",
            issue_type=IssueType.PLAN,
            changespec_bug_id="12345",
        )
        with pytest.raises(ValueError, match="requires changespec_name"):
            issue.validate()

    def test_resolution_requires_closed_status(self) -> None:
        issue = Issue(
            id="test-1",
            title="A plan",
            issue_type=IssueType.PLAN,
            resolution=Resolution.DONE,
        )
        with pytest.raises(ValueError, match="Only closed issues"):
            issue.validate()

        issue.status = Status.CLOSED
        issue.validate()


class TestDependency:
    def test_dependency_fields(self) -> None:
        dep = Dependency(
            issue_id="a",
            depends_on_id="b",
            created_at="2026-01-01T00:00:00Z",
            created_by="user",
        )
        assert dep.issue_id == "a"
        assert dep.depends_on_id == "b"
        assert dep.created_at == "2026-01-01T00:00:00Z"
        assert dep.created_by == "user"

    def test_dependency_default_created_by(self) -> None:
        dep = Dependency(
            issue_id="a",
            depends_on_id="b",
            created_at="2026-01-01T00:00:00Z",
        )
        assert dep.created_by == ""


class TestEnums:
    def test_status_values(self) -> None:
        assert Status.OPEN.value == "open"
        assert Status.CLAIMED.value == "claimed"
        assert Status.READY.value == "ready"
        assert Status.IN_PROGRESS.value == "in_progress"
        assert Status.CLOSED.value == "closed"

    def test_issue_type_values(self) -> None:
        assert IssueType.PLAN.value == "plan"
        assert IssueType.PHASE.value == "phase"
        assert IssueType.TASK.value == "task"

    def test_resolution_values(self) -> None:
        assert [resolution.value for resolution in Resolution] == [
            "done",
            "canceled",
            "superseded",
        ]
