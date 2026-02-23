"""Tests for parent-passed check for proposals and fix-hook exceptions."""

from sase.ace.changespec import HookEntry, HookStatusLine
from sase.ace.hooks import get_entries_needing_hook_run, hook_needs_run


def _make_hook_with_status_lines(
    command: str,
    status_lines: list[HookStatusLine],
) -> HookEntry:
    """Helper function to create a HookEntry with multiple status lines."""
    return HookEntry(command=command, status_lines=status_lines)


def test_hook_needs_run_proposal_waits_no_parent_status() -> None:
    """Test that proposal waits when parent has no status line."""
    # Hook with no status lines at all
    hook = HookEntry(command="make test")
    # Proposal "2a" should wait - parent "2" has no status
    assert hook_needs_run(hook, "2a") is False
    # But regular entry "1" can still run
    assert hook_needs_run(hook, "1") is True


def test_hook_needs_run_fix_hook_exception() -> None:
    """Test that fix-hook proposal runs immediately (parent suffix matches)."""
    hook = _make_hook_with_status_lines(
        "make test",
        [
            HookStatusLine(
                commit_entry_num="2",
                timestamp="251231_120000",
                status="FAILED",
                suffix="2a",  # Fix-hook created proposal "2a"
            )
        ],
    )
    # Proposal "2a" can run - it's the fix-hook proposal for this hook
    assert hook_needs_run(hook, "2a") is True
    # But proposal "2b" still waits - it's not the fix-hook proposal
    assert hook_needs_run(hook, "2b") is False


def test_get_entries_needing_hook_run_parent_passed() -> None:
    """Test get_entries_needing_hook_run respects parent-passed for proposals."""
    # Parent "2" passed
    hook = _make_hook_with_status_lines(
        "make test",
        [
            HookStatusLine(
                commit_entry_num="2", timestamp="251231_120000", status="PASSED"
            )
        ],
    )
    # Should return both regular "3" and proposal "2a" (parent passed)
    result = get_entries_needing_hook_run(hook, ["2", "2a", "3"])
    assert "3" in result  # Regular entry needs to run
    assert "2a" in result  # Proposal can run - parent passed
    assert "2" not in result  # Already has status


def test_get_entries_needing_hook_run_parent_not_passed() -> None:
    """Test get_entries_needing_hook_run skips proposals when parent not passed."""
    # Parent "2" is running
    hook = _make_hook_with_status_lines(
        "make test",
        [
            HookStatusLine(
                commit_entry_num="2", timestamp="251231_120000", status="RUNNING"
            )
        ],
    )
    # Should only return regular "3", not proposal "2a"
    result = get_entries_needing_hook_run(hook, ["2", "2a", "3"])
    assert "3" in result  # Regular entry needs to run
    assert "2a" not in result  # Proposal waits - parent not passed
    assert "2" not in result  # Already has status
