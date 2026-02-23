"""Tests for timestamp handling, suffix detection, and hook command prefixes."""

from sase.ace.changespec import HookEntry
from sase.ace.hooks import (
    generate_timestamp,
    hook_needs_run,
    is_suffix_stale,
)


# Tests for is_timestamp_suffix
# Tests for is_suffix_stale
def test_is_suffix_stale_recent_timestamp() -> None:
    """Test is_suffix_stale returns False for recent timestamps."""
    # Use generate_timestamp() to get a fresh timestamp
    recent = generate_timestamp()
    assert is_suffix_stale(recent) is False


# Tests for generate_timestamp format
# Tests for timestamp parsing
# Tests for HookEntry prefix properties
def test_hook_entry_no_prefix() -> None:
    """Test hook without any prefix."""
    hook = HookEntry(command="some_command")
    assert hook.skip_fix_hook is False
    assert hook.skip_proposal_runs is False
    assert hook.display_command == "some_command"
    assert hook.run_command == "some_command"


def test_hook_entry_is_unlimited_with_dollar() -> None:
    """Test is_unlimited is True when command has '$' prefix."""
    assert HookEntry(command="$some_command").is_unlimited is True
    assert HookEntry(command="!$some_command").is_unlimited is True
    assert HookEntry(command="!some_command").is_unlimited is False
    assert HookEntry(command="some_command").is_unlimited is False


def test_hook_needs_run_skips_combined_prefix_for_proposals() -> None:
    """Test that '!$' prefixed hooks are skipped for proposal entries."""
    # Hook with !$ prefix should be skipped for proposal entries (due to $)
    hook_with_both = HookEntry(command="!$some_command")
    assert hook_needs_run(hook_with_both, "1a") is False
    # But should run for regular entries
    assert hook_needs_run(hook_with_both, "1") is True
