"""Tests for summarize-hook workflow eligibility and behavior."""

from sase.ace.changespec import HookEntry, HookStatusLine
from sase.ace.hooks.workflow_queries import get_failing_hooks_for_summarize


def _make_hook_with_status(
    command: str,
    commit_entry_num: str,
    status: str,
    suffix: str | None = None,
) -> HookEntry:
    """Helper to create a HookEntry with a specific status line."""
    status_line = HookStatusLine(
        commit_entry_num=commit_entry_num,
        timestamp="241228_120000",
        status=status,
        duration="1m23s",
        suffix=suffix,
    )
    return HookEntry(command=command, status_lines=[status_line])


def test_get_failing_hooks_for_summarize_proposal_entry_letter_b() -> None:
    """Test that proposal entries with letter 'b' are also eligible."""
    hook = _make_hook_with_status(
        command="make lint",
        commit_entry_num="3b",  # Proposal entry with 'b'
        status="FAILED",
        suffix=None,
    )
    result = get_failing_hooks_for_summarize([hook])
    assert len(result) == 1
    assert result[0].command == "make lint"


def test_get_failing_hooks_for_summarize_regular_entry() -> None:
    """Test that regular entry FAILED hooks are NOT eligible for summarize."""
    hook = _make_hook_with_status(
        command="make test",
        commit_entry_num="2",  # Regular entry (no letter)
        status="FAILED",
        suffix=None,
    )
    result = get_failing_hooks_for_summarize([hook])
    assert len(result) == 0
