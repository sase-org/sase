"""Tests for workflow operations and available workflows."""

from sase.ace.changespec import ChangeSpec, CommentEntry, HookEntry, HookStatusLine
from sase.ace.operations import get_available_workflows


def _make_hook(
    command: str,
    commit_entry_num: str = "1",
    timestamp: str | None = None,
    status: str | None = None,
    duration: str | None = None,
) -> HookEntry:
    """Helper function to create a HookEntry with a status line."""
    if timestamp is None and status is None:
        return HookEntry(command=command)
    status_line = HookStatusLine(
        commit_entry_num=commit_entry_num,
        timestamp=timestamp or "",
        status=status or "",
        duration=duration,
    )
    return HookEntry(command=command, status_lines=[status_line])


def test_get_available_workflows_with_comments_entry() -> None:
    """Test that COMMENTS entry without suffix returns crs workflow."""
    cs = ChangeSpec(
        name="Test",
        description="Test",
        parent="None",
        cl="123",
        test_targets=None,
        status="Mailed",
        file_path="/tmp/test.md",
        line_number=1,
        kickstart=None,
        comments=[
            CommentEntry(
                reviewer="critique",
                file_path="~/.sase/comments/test-critique-241226_120000.json",
                suffix=None,  # No suffix = CRS available
            )
        ],
    )
    workflows = get_available_workflows(cs)
    assert workflows == ["crs"]


def test_get_available_workflows_with_non_test_target_failed_hook() -> None:
    """Test that failing non-test hooks trigger fix-hook workflow."""
    cs = ChangeSpec(
        name="Test",
        description="Test",
        parent="None",
        cl="123",
        test_targets=None,
        status="Ready",
        file_path="/tmp/test.md",
        line_number=1,
        kickstart=None,
        hooks=[
            _make_hook(command="flake8 src", status="FAILED"),
        ],
    )
    workflows = get_available_workflows(cs)
    # fix-hook is available for any failing hook
    assert workflows == ["fix-hook"]


def test_get_available_workflows_all_hooks_passing() -> None:
    """Test that no fix-hook workflow when all hooks passing."""
    cs = ChangeSpec(
        name="Test",
        description="Test",
        parent="None",
        cl="123",
        test_targets=None,
        status="Ready",
        file_path="/tmp/test.md",
        line_number=1,
        kickstart=None,
        hooks=[
            _make_hook(command="bb_rabbit_test //target1", status="PASSED"),
            _make_hook(command="flake8 src", status="PASSED"),
        ],
    )
    workflows = get_available_workflows(cs)
    assert workflows == []
