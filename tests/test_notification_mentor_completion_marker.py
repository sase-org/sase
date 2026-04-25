"""Tests for the mentor completion notification idempotency marker."""

from sase.notifications.mentor_completion_marker import (
    is_notified,
    mark_notified,
)


def test_is_notified_returns_false_when_no_marker_file() -> None:
    assert is_notified("/proj.gp", "cl-1", "1") is False


def test_mark_then_is_notified_returns_true() -> None:
    mark_notified("/proj.gp", "cl-1", "1")
    assert is_notified("/proj.gp", "cl-1", "1") is True


def test_marker_isolated_per_entry_id() -> None:
    mark_notified("/proj.gp", "cl-1", "1")
    assert is_notified("/proj.gp", "cl-1", "2") is False


def test_marker_isolated_per_changespec() -> None:
    mark_notified("/proj.gp", "cl-1", "1")
    assert is_notified("/proj.gp", "cl-2", "1") is False


def test_marker_isolated_per_project_file() -> None:
    mark_notified("/proj-a.gp", "cl-1", "1")
    assert is_notified("/proj-b.gp", "cl-1", "1") is False


def test_mark_is_idempotent() -> None:
    mark_notified("/proj.gp", "cl-1", "1")
    mark_notified("/proj.gp", "cl-1", "1")
    assert is_notified("/proj.gp", "cl-1", "1") is True


def test_mark_multiple_entries() -> None:
    mark_notified("/proj.gp", "cl-1", "1")
    mark_notified("/proj.gp", "cl-1", "2")
    mark_notified("/proj.gp", "cl-2", "1")
    assert is_notified("/proj.gp", "cl-1", "1") is True
    assert is_notified("/proj.gp", "cl-1", "2") is True
    assert is_notified("/proj.gp", "cl-2", "1") is True
    assert is_notified("/proj.gp", "cl-2", "2") is False
