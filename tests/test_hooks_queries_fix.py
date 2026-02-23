"""Tests for fix-hook workflow query functions."""

from sase.ace.changespec import (
    HookEntry,
    HookStatusLine,
)


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


# Tests for get_failing_hooks_for_fix
def test_get_failing_hooks_for_fix_excludes_proposals() -> None:
    """Test that proposal entries (like '2a') are excluded from fix-hook."""
    from sase.ace.hooks.workflow_queries import get_failing_hooks_for_fix

    hook = HookEntry(
        command="flake8 src",
        status_lines=[
            HookStatusLine(
                commit_entry_num="2a",
                timestamp="240601_123456",
                status="FAILED",
            )
        ],
    )
    failing = get_failing_hooks_for_fix([hook])
    assert len(failing) == 0


def test_get_failing_hooks_for_fix_excludes_hooks_with_suffix() -> None:
    """Test that hooks with suffix are excluded from fix-hook."""
    from sase.ace.hooks.workflow_queries import get_failing_hooks_for_fix

    hook = HookEntry(
        command="flake8 src",
        status_lines=[
            HookStatusLine(
                commit_entry_num="1",
                timestamp="240601_123456",
                status="FAILED",
                suffix="running_agent",
            )
        ],
    )
    failing = get_failing_hooks_for_fix([hook])
    assert len(failing) == 0


# Tests for get_failing_hook_entries_for_fix
def test_get_failing_hook_entries_for_fix_excludes_proposals() -> None:
    """Test that proposal entry IDs are excluded from fix-hook."""
    from sase.ace.hooks.workflow_queries import get_failing_hook_entries_for_fix

    hook = HookEntry(
        command="flake8 src",
        status_lines=[
            HookStatusLine(
                commit_entry_num="3a",
                timestamp="240601_123456",
                status="FAILED",
                suffix="summary",
                suffix_type="summarize_complete",
            )
        ],
    )
    result = get_failing_hook_entries_for_fix([hook], ["3a"])
    assert len(result) == 0


def test_get_failing_hook_entries_for_fix_requires_summarize_complete() -> None:
    """Test that only entries with summarize_complete suffix are included."""
    from sase.ace.hooks.workflow_queries import get_failing_hook_entries_for_fix

    hook = HookEntry(
        command="flake8 src",
        status_lines=[
            HookStatusLine(
                commit_entry_num="3",
                timestamp="240601_123456",
                status="FAILED",
                suffix="running",
                suffix_type="running_agent",
            )
        ],
    )
    result = get_failing_hook_entries_for_fix([hook], ["3"])
    assert len(result) == 0


def test_get_failing_hook_entries_for_fix_requires_suffix() -> None:
    """Test that entries without suffix are excluded from fix-hook."""
    from sase.ace.hooks.workflow_queries import get_failing_hook_entries_for_fix

    hook = HookEntry(
        command="flake8 src",
        status_lines=[
            HookStatusLine(
                commit_entry_num="3",
                timestamp="240601_123456",
                status="FAILED",
                suffix_type="summarize_complete",
                suffix=None,
            )
        ],
    )
    result = get_failing_hook_entries_for_fix([hook], ["3"])
    assert len(result) == 0


def test_get_failing_hook_entries_for_fix_multiple_entries() -> None:
    """Test checking multiple entry IDs across multiple hooks."""
    from sase.ace.hooks.workflow_queries import get_failing_hook_entries_for_fix

    hooks = [
        HookEntry(
            command="flake8 src",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="2",
                    timestamp="240601_100000",
                    status="FAILED",
                    suffix="summary1",
                    suffix_type="summarize_complete",
                ),
                HookStatusLine(
                    commit_entry_num="3",
                    timestamp="240601_110000",
                    status="PASSED",
                ),
            ],
        ),
        HookEntry(
            command="pytest tests",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="2",
                    timestamp="240601_120000",
                    status="FAILED",
                    suffix="summary2",
                    suffix_type="summarize_complete",
                ),
            ],
        ),
    ]
    result = get_failing_hook_entries_for_fix(hooks, ["2", "3"])
    assert len(result) == 2
    commands = [r[0].command for r in result]
    assert "flake8 src" in commands
    assert "pytest tests" in commands


def test_get_failing_hook_entries_for_fix_no_status_lines() -> None:
    """Test that hooks with no status_lines return empty results."""
    from sase.ace.hooks.workflow_queries import get_failing_hook_entries_for_fix

    hooks = [HookEntry(command="flake8 src")]
    result = get_failing_hook_entries_for_fix(hooks, ["1", "2"])
    assert len(result) == 0


# Tests for has_failing_hooks_for_fix
def test_get_failing_hooks_for_fix_excludes_skip_fix_hook() -> None:
    """Test that hooks with ! prefix (skip_fix_hook) are excluded."""
    from sase.ace.hooks.workflow_queries import get_failing_hooks_for_fix

    hook = HookEntry(
        command="!sase_hg_presubmit",
        status_lines=[
            HookStatusLine(
                commit_entry_num="1",
                timestamp="240601_123456",
                status="FAILED",
            )
        ],
    )
    failing = get_failing_hooks_for_fix([hook])
    assert len(failing) == 0


def test_get_failing_hook_entries_for_fix_excludes_skip_fix_hook() -> None:
    """Test that hooks with ! prefix (skip_fix_hook) are excluded from fix."""
    from sase.ace.hooks.workflow_queries import get_failing_hook_entries_for_fix

    hook = HookEntry(
        command="!sase_hg_presubmit",
        status_lines=[
            HookStatusLine(
                commit_entry_num="3",
                timestamp="240601_123456",
                status="FAILED",
                suffix="summary text",
                suffix_type="summarize_complete",
            )
        ],
    )
    result = get_failing_hook_entries_for_fix([hook], ["3"])
    assert len(result) == 0
