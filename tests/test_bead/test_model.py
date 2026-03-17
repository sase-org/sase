"""Tests for issue and dependency models."""

import pytest

from sase.bead.model import Dependency, Issue, IssueType, Status


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
