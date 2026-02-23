"""Tests for hook_has_any_running_status function."""

from sase.ace.changespec import HookEntry, HookStatusLine
from sase.ace.hooks import hook_has_any_running_status


def _make_hook_with_status_lines(
    command: str,
    status_lines: list[HookStatusLine],
) -> HookEntry:
    """Helper function to create a HookEntry with multiple status lines."""
    return HookEntry(command=command, status_lines=status_lines)


def test_hook_has_any_running_status_no_status_lines() -> None:
    """Test hook_has_any_running_status with no status lines returns False."""
    hook = HookEntry(command="make test")
    assert hook_has_any_running_status(hook) is False
