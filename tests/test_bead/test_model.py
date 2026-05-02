"""Tests for issue and dependency models."""

import pytest

from sase.bead.model import BeadTier, Dependency, Issue, IssueType, Status


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
        with pytest.raises(ValueError, match="Phase issues cannot carry"):
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
        assert Status.IN_PROGRESS.value == "in_progress"
        assert Status.CLOSED.value == "closed"

    def test_issue_type_values(self) -> None:
        assert IssueType.PLAN.value == "plan"
        assert IssueType.PHASE.value == "phase"
