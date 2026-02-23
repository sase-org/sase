"""Tests for ChangeSpec navigation history (ctrl+o / ctrl+i)."""

from sase.ace.tui.changespec_history import (
    MAX_STACK_SIZE,
    ChangeSpecHistoryEntry,
    ChangeSpecHistoryStacks,
    create_empty_stacks,
    navigate_next,
    navigate_prev,
    push_to_prev_stack,
)


def _make_entry(
    name: str, file_path: str = "/test/project.gp", query: str = "*"
) -> ChangeSpecHistoryEntry:
    """Helper to create a test entry."""
    return ChangeSpecHistoryEntry(name=name, file_path=file_path, query=query)


def test_changespec_history_entry_dataclass() -> None:
    """Test that ChangeSpecHistoryEntry stores all fields."""
    entry = ChangeSpecHistoryEntry(
        name="my-cl",
        file_path="/home/.sase/projects/test/test.gp",
        query="status:WIP",
    )
    assert entry.name == "my-cl"
    assert entry.file_path == "/home/.sase/projects/test/test.gp"
    assert entry.query == "status:WIP"


def test_push_to_prev_no_duplicates() -> None:
    """Test that pushing entry removes existing duplicate (by name/file_path)."""
    stacks = ChangeSpecHistoryStacks(
        prev=[
            _make_entry("old"),
            _make_entry("current", query="query1"),
            _make_entry("other"),
        ],
        next=[],
    )
    # Push same name/file_path with different query
    push_to_prev_stack(_make_entry("current", query="query2"), stacks)
    # "current" removed from middle and added to end with new query
    assert len(stacks.prev) == 3
    assert stacks.prev[0].name == "old"
    assert stacks.prev[1].name == "other"
    assert stacks.prev[2].name == "current"
    assert stacks.prev[2].query == "query2"


def test_navigate_prev_empty() -> None:
    """Test navigating prev when stack is empty."""
    stacks = create_empty_stacks()
    result = navigate_prev(_make_entry("current"), stacks)
    assert result is None
    assert stacks.prev == []
    assert stacks.next == []


def test_navigate_next_empty() -> None:
    """Test navigating next when stack is empty."""
    stacks = create_empty_stacks()
    result = navigate_next(_make_entry("current"), stacks)
    assert result is None
    assert stacks.prev == []
    assert stacks.next == []


def test_max_stack_size_on_push() -> None:
    """Test that push enforces max size."""
    entries = [_make_entry(f"cl{i}") for i in range(MAX_STACK_SIZE)]
    stacks = ChangeSpecHistoryStacks(prev=entries, next=[])
    push_to_prev_stack(_make_entry("new"), stacks)
    assert len(stacks.prev) == MAX_STACK_SIZE
    # Should keep most recent entries (including the new one)
    assert stacks.prev[-1].name == "new"
    assert stacks.prev[0].name == "cl1"  # cl0 dropped


def test_round_trip_navigation() -> None:
    """Test navigating back and forth preserves entries."""
    stacks = ChangeSpecHistoryStacks(
        prev=[_make_entry("cl1"), _make_entry("cl2")],
        next=[],
    )

    # Navigate back twice
    r1 = navigate_prev(_make_entry("cl3"), stacks)
    assert r1 is not None and r1.name == "cl2"
    r2 = navigate_prev(_make_entry("cl2"), stacks)
    assert r2 is not None and r2.name == "cl1"

    # Navigate forward twice
    r3 = navigate_next(_make_entry("cl1"), stacks)
    assert r3 is not None and r3.name == "cl2"
    r4 = navigate_next(_make_entry("cl2"), stacks)
    assert r4 is not None and r4.name == "cl3"

    # Final state: back where we started
    assert len(stacks.prev) == 2
    assert stacks.prev[0].name == "cl1"
    assert stacks.prev[1].name == "cl2"
    assert stacks.next == []
