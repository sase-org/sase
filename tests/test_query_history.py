"""Tests for query history stacks functionality."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.query_history import (
    MAX_STACK_SIZE,
    QueryHistoryStacks,
    load_all_query_history,
    load_query_history,
    navigate_next,
    navigate_prev,
    push_to_prev_stack,
    save_all_query_history,
    save_query_history,
    snapshot_query_history,
)
from sase.ace.query_record import QueryRecord


def _record(text: str) -> QueryRecord:
    return QueryRecord(source=text, canonical=text)


def test_load_empty_when_no_file(tmp_path: Path) -> None:
    """Test loading returns empty stacks when no file exists."""
    with patch(
        "sase.ace.query_history._QUERY_HISTORY_FILE", tmp_path / "nonexistent.json"
    ):
        result = load_query_history("patches")
        assert result.prev == []
        assert result.next == []


def test_navigate_prev_empty() -> None:
    """Test navigating prev when stack is empty."""
    stacks = QueryHistoryStacks(prev=[], next=[])
    result = navigate_prev(_record("current"), stacks)
    assert result is None
    assert stacks.prev == []
    assert stacks.next == []


def test_navigate_prev_removes_duplicate_from_next() -> None:
    """Test that navigate_prev removes duplicate from next stack."""
    stacks = QueryHistoryStacks(
        prev=[_record("old")],
        next=[_record("future"), _record("current"), _record("other")],
    )
    result = navigate_prev(_record("current"), stacks)
    assert result == _record("old")
    assert stacks.prev == []
    # "current" removed from middle of next stack and moved to end
    assert stacks.next == [_record("future"), _record("other"), _record("current")]


def test_navigate_next_empty() -> None:
    """Test navigating next when stack is empty."""
    stacks = QueryHistoryStacks(prev=[], next=[])
    result = navigate_next(_record("current"), stacks)
    assert result is None
    assert stacks.prev == []
    assert stacks.next == []


def test_navigate_next_success() -> None:
    """Test successful next navigation."""
    stacks = QueryHistoryStacks(prev=[], next=[_record("future1"), _record("future2")])
    result = navigate_next(_record("current"), stacks)
    assert result == _record("future2")
    assert stacks.prev == [_record("current")]
    assert stacks.next == [_record("future1")]


def test_max_stack_size_on_push() -> None:
    """Test that push enforces max size."""
    stacks = QueryHistoryStacks(
        prev=[_record(f"q{i}") for i in range(MAX_STACK_SIZE)], next=[]
    )
    push_to_prev_stack(_record("new"), stacks)
    assert len(stacks.prev) == MAX_STACK_SIZE
    # Should keep most recent entries (including the new one)
    assert stacks.prev[-1] == _record("new")
    assert stacks.prev[0] == _record("q1")  # q0 dropped


def test_handles_corrupt_json(tmp_path: Path) -> None:
    """Test that corrupt JSON files are handled gracefully."""
    test_file = tmp_path / "query_history.json"
    test_file.write_text("not valid json {")
    with patch("sase.ace.query_history._QUERY_HISTORY_FILE", test_file):
        result = load_query_history("patches")
        assert result.prev == []
        assert result.next == []


def test_empty_stacks_dataclass() -> None:
    """Test that empty QueryHistoryStacks can be created."""
    stacks = QueryHistoryStacks(prev=[], next=[])
    assert stacks.prev == []
    assert stacks.next == []


def test_save_and_load_is_namespaced_per_pane(tmp_path: Path) -> None:
    """Two panes keep independent history stacks."""
    test_file = tmp_path / "query_history.json"
    with patch("sase.ace.query_history._QUERY_HISTORY_FILE", test_file):
        save_query_history("patches", QueryHistoryStacks(prev=[_record("p")], next=[]))
        save_query_history("stitches", QueryHistoryStacks(prev=[_record("s")], next=[]))

        assert load_query_history("patches").prev == [_record("p")]
        assert load_query_history("stitches").prev == [_record("s")]


def test_load_and_save_all_query_history(tmp_path: Path) -> None:
    """Whole-map helpers preserve pane isolation for in-memory app state."""
    test_file = tmp_path / "query_history.json"
    with patch("sase.ace.query_history._QUERY_HISTORY_FILE", test_file):
        save_all_query_history(
            {
                "patches": QueryHistoryStacks(prev=[_record("p")], next=[]),
                "beads": QueryHistoryStacks(
                    prev=[_record("b1")],
                    next=[_record("b2")],
                ),
            }
        )

        result = load_all_query_history()
        assert result["patches"].prev == [_record("p")]
        assert result["beads"].prev == [_record("b1")]
        assert result["beads"].next == [_record("b2")]


def test_snapshot_query_history_is_detached() -> None:
    """Background writers receive a copy, not live mutable stacks."""
    panes = {"beads": QueryHistoryStacks(prev=[_record("old")], next=[])}
    snapshot = snapshot_query_history(panes)

    panes["beads"].prev.append(_record("new"))

    assert snapshot["beads"].prev == [_record("old")]


def test_load_query_history_migrates_legacy_flat_file(tmp_path: Path) -> None:
    """A legacy flat file is lifted under the patches pane on first read."""
    import json

    test_file = tmp_path / "query_history.json"
    test_file.write_text(json.dumps({"prev": ["status:Ready", '"alpha"'], "next": []}))
    with patch("sase.ace.query_history._QUERY_HISTORY_FILE", test_file):
        result = load_query_history("patches")
        assert result.prev == [_record("status:Ready"), _record('"alpha"')]
        assert result.next == []
        assert load_query_history("stitches") == QueryHistoryStacks(prev=[], next=[])
