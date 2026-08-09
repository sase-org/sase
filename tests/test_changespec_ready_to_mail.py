"""Tests for ready-to-mail helper functions in patch module."""

from sase.ace.patch import (
    Patch,
    CommitEntry,
    HookEntry,
    HookStatusLine,
    all_hooks_passed_for_entries,
    get_current_and_proposal_entry_ids,
)


def _make_patch(
    commits: list | None = None,
    hooks: list | None = None,
    status: str = "Ready",
) -> Patch:
    """Helper function to create a Patch with required fields for tests."""
    return Patch(
        name="test",
        description="test",
        parent=None,
        cl=None,
        status=status,
        file_path="/tmp/test.sase",
        line_number=1,
        commits=commits,
        hooks=hooks,
    )


# Tests for get_current_and_proposal_entry_ids
def test_get_current_and_proposal_entry_ids_with_proposals() -> None:
    """Test returns current + proposals with same number."""
    patch = _make_patch(
        commits=[
            CommitEntry(number=1, note="First change"),
            CommitEntry(number=2, note="Second change"),
            CommitEntry(number=2, note="Proposal A", proposal_letter="a"),
            CommitEntry(number=2, note="Proposal B", proposal_letter="b"),
        ],
    )
    result = get_current_and_proposal_entry_ids(patch)
    assert result == ["2", "2a", "2b"]


def test_get_current_and_proposal_entry_ids_all_proposals() -> None:
    """Test returns empty list when all entries are proposals (no current)."""
    patch = _make_patch(
        commits=[
            CommitEntry(number=1, note="Only proposal", proposal_letter="a"),
        ],
    )
    result = get_current_and_proposal_entry_ids(patch)
    assert result == []


# Tests for all_hooks_passed_for_entries
def test_all_hooks_passed_for_entries_one_failed() -> None:
    """Test returns False when one hook has FAILED."""
    hooks = [
        HookEntry(
            command="hook1",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="2", timestamp="240601_120000", status="PASSED"
                ),
            ],
        ),
        HookEntry(
            command="hook2",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="2", timestamp="240601_120000", status="FAILED"
                ),
            ],
        ),
    ]
    patch = _make_patch(hooks=hooks)
    result = all_hooks_passed_for_entries(patch, ["2"])
    assert result is False


def test_all_hooks_passed_for_entries_no_status() -> None:
    """Test returns False when hook has no status line for an entry."""
    hooks = [
        HookEntry(
            command="hook1",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="2", timestamp="240601_120000", status="PASSED"
                ),
                # No status line for "2a"
            ],
        ),
    ]
    patch = _make_patch(hooks=hooks)
    result = all_hooks_passed_for_entries(patch, ["2", "2a"])
    assert result is False


def test_all_hooks_passed_for_entries_skip_dollar_no_status() -> None:
    """Test that $-prefixed hooks without status are also skipped."""
    hooks = [
        HookEntry(
            command="$hook_with_dollar_prefix",
            status_lines=[],  # No status lines at all
        ),
    ]
    patch = _make_patch(hooks=hooks)
    # Should pass because $-prefixed hooks are completely skipped
    result = all_hooks_passed_for_entries(patch, ["2"])
    assert result is True
