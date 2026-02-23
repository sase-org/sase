"""Tests for query history stacks functionality."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.query_history import (
    MAX_STACK_SIZE,
    QueryHistoryStacks,
    load_query_history,
    navigate_next,
    navigate_prev,
    push_to_prev_stack,
)


def test_load_empty_when_no_file(tmp_path: Path) -> None:
    """Test loading returns empty stacks when no file exists."""
    with patch(
        "sase.ace.query_history._QUERY_HISTORY_FILE", tmp_path / "nonexistent.json"
    ):
        result = load_query_history()
        assert result.prev == []
        assert result.next == []


def test_navigate_prev_empty() -> None:
    """Test navigating prev when stack is empty."""
    stacks = QueryHistoryStacks(prev=[], next=[])
    result = navigate_prev("current", stacks)
    assert result is None
    assert stacks.prev == []
    assert stacks.next == []


def test_navigate_prev_removes_duplicate_from_next() -> None:
    """Test that navigate_prev removes duplicate from next stack."""
    stacks = QueryHistoryStacks(prev=["old"], next=["future", "current", "other"])
    result = navigate_prev("current", stacks)
    assert result == "old"
    assert stacks.prev == []
    # "current" removed from middle of next stack and moved to end
    assert stacks.next == ["future", "other", "current"]


def test_navigate_next_empty() -> None:
    """Test navigating next when stack is empty."""
    stacks = QueryHistoryStacks(prev=[], next=[])
    result = navigate_next("current", stacks)
    assert result is None
    assert stacks.prev == []
    assert stacks.next == []


def test_navigate_next_success() -> None:
    """Test successful next navigation."""
    stacks = QueryHistoryStacks(prev=[], next=["future1", "future2"])
    result = navigate_next("current", stacks)
    assert result == "future2"
    assert stacks.prev == ["current"]
    assert stacks.next == ["future1"]


def test_max_stack_size_on_push() -> None:
    """Test that push enforces max size."""
    stacks = QueryHistoryStacks(prev=[f"q{i}" for i in range(MAX_STACK_SIZE)], next=[])
    push_to_prev_stack("new", stacks)
    assert len(stacks.prev) == MAX_STACK_SIZE
    # Should keep most recent entries (including the new one)
    assert stacks.prev[-1] == "new"
    assert stacks.prev[0] == "q1"  # q0 dropped


def test_handles_corrupt_json(tmp_path: Path) -> None:
    """Test that corrupt JSON files are handled gracefully."""
    test_file = tmp_path / "query_history.json"
    test_file.write_text("not valid json {")
    with patch("sase.ace.query_history._QUERY_HISTORY_FILE", test_file):
        result = load_query_history()
        assert result.prev == []
        assert result.next == []


def test_empty_stacks_dataclass() -> None:
    """Test that empty QueryHistoryStacks can be created."""
    stacks = QueryHistoryStacks(prev=[], next=[])
    assert stacks.prev == []
    assert stacks.next == []
