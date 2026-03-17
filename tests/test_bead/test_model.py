"""Tests for issue and dependency models."""

import pytest

from sase.bead.model import Dependency, Issue, IssueType, Status


class TestIssueValidation:
    def test_valid_child_with_parent(self) -> None:
        issue = Issue(
            id="test-1",
            title="A child",
            issue_type=IssueType.CHILD,
            parent_id="test-0",
        )
        issue.validate()  # Should not raise

    def test_child_without_parent_raises(self) -> None:
        issue = Issue(
            id="test-1",
            title="A child",
            issue_type=IssueType.CHILD,
            parent_id=None,
        )
        with pytest.raises(ValueError, match="Child issues must have a parent_id"):
            issue.validate()

    def test_valid_epic_without_parent(self) -> None:
        issue = Issue(
            id="test-1",
            title="An epic",
            issue_type=IssueType.EPIC,
            parent_id=None,
        )
        issue.validate()  # Should not raise

    def test_epic_with_parent_raises(self) -> None:
        issue = Issue(
            id="test-1",
            title="An epic",
            issue_type=IssueType.EPIC,
            parent_id="test-0",
        )
        with pytest.raises(ValueError, match="Epic issues must not have a parent_id"):
            issue.validate()

    def test_default_status_is_open(self) -> None:
        issue = Issue(id="test-1", title="Test")
        assert issue.status == Status.OPEN

    def test_default_type_is_child(self) -> None:
        issue = Issue(id="test-1", title="Test")
        assert issue.issue_type == IssueType.CHILD


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
        assert IssueType.EPIC.value == "epic"
        assert IssueType.CHILD.value == "child"
