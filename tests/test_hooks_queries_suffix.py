"""Tests for suffix operations and utility query functions."""

from sase.ace.changespec import (
    HookEntry,
    HookStatusLine,
)


# Tests for apply_hook_suffix_update
def testapply_hook_suffix_update_with_entry_id() -> None:
    """Test applying suffix update to a specific entry ID."""
    from sase.ace.hooks.mutations import apply_hook_suffix_update

    hooks = [
        HookEntry(
            command="flake8 src",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="240601_100000",
                    status="PASSED",
                ),
                HookStatusLine(
                    commit_entry_num="2",
                    timestamp="240601_110000",
                    status="FAILED",
                ),
            ],
        ),
    ]
    updated, was_updated = apply_hook_suffix_update(
        hooks, "flake8 src", "suffix_for_entry1", entry_id="1"
    )
    assert was_updated is True
    assert updated[0].status_lines is not None
    sl1 = [sl for sl in updated[0].status_lines if sl.commit_entry_num == "1"][0]
    assert sl1.suffix == "suffix_for_entry1"
    sl2 = [sl for sl in updated[0].status_lines if sl.commit_entry_num == "2"][0]
    assert sl2.suffix is None


def testapply_hook_suffix_update_with_summary() -> None:
    """Test applying suffix update with summary."""
    from sase.ace.hooks.mutations import apply_hook_suffix_update

    hooks = [
        HookEntry(
            command="flake8 src",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="240601_123456",
                    status="FAILED",
                )
            ],
        ),
    ]
    updated, was_updated = apply_hook_suffix_update(
        hooks,
        "flake8 src",
        "fix_attempt",
        suffix_type="summarize_complete",
        summary="Brief summary of the issue",
    )
    assert was_updated is True
    assert updated[0].status_lines is not None
    sl = updated[0].status_lines[0]
    assert sl.suffix == "fix_attempt"
    assert sl.suffix_type == "summarize_complete"
    assert sl.summary == "Brief summary of the issue"


def testapply_hook_suffix_update_no_match() -> None:
    """Test that non-matching hooks are unchanged."""
    from sase.ace.hooks.mutations import apply_hook_suffix_update

    hooks = [
        HookEntry(
            command="flake8 src",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="240601_123456",
                    status="FAILED",
                )
            ],
        ),
    ]
    updated, was_updated = apply_hook_suffix_update(hooks, "pytest tests", "suffix")
    assert was_updated is False
    assert updated[0].status_lines is not None
    assert updated[0].status_lines[0].suffix is None


def testapply_hook_suffix_update_no_status_lines() -> None:
    """Test applying suffix to hook with no status lines."""
    from sase.ace.hooks.mutations import apply_hook_suffix_update

    hooks = [HookEntry(command="flake8 src")]
    updated, was_updated = apply_hook_suffix_update(hooks, "flake8 src", "suffix")
    assert was_updated is False
    assert updated[0].command == "flake8 src"
    assert updated[0].status_lines is None


# Tests for apply_clear_hook_suffix
def testapply_clear_hook_suffix_no_suffix() -> None:
    """Test clearing when there's no suffix to clear."""
    from sase.ace.hooks.mutations import apply_clear_hook_suffix

    hooks = [
        HookEntry(
            command="flake8 src",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="240601_123456",
                    status="FAILED",
                    suffix=None,
                )
            ],
        ),
    ]
    updated, was_cleared = apply_clear_hook_suffix(hooks, "flake8 src")
    assert was_cleared is False
    assert updated[0].status_lines is not None
    assert updated[0].status_lines[0].suffix is None


def testapply_clear_hook_suffix_no_status_lines() -> None:
    """Test clearing suffix on hook with no status lines."""
    from sase.ace.hooks.mutations import apply_clear_hook_suffix

    hooks = [HookEntry(command="flake8 src")]
    updated, was_cleared = apply_clear_hook_suffix(hooks, "flake8 src")
    assert was_cleared is False
    assert updated[0].command == "flake8 src"
    assert updated[0].status_lines is None


def testapply_clear_hook_suffix_multiple_hooks() -> None:
    """Test clearing suffix when there are multiple hooks."""
    from sase.ace.hooks.mutations import apply_clear_hook_suffix

    hooks = [
        HookEntry(
            command="flake8 src",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="240601_100000",
                    status="FAILED",
                    suffix="suffix_to_keep",
                )
            ],
        ),
        HookEntry(
            command="pytest tests",
            status_lines=[
                HookStatusLine(
                    commit_entry_num="1",
                    timestamp="240601_110000",
                    status="FAILED",
                    suffix="suffix_to_clear",
                )
            ],
        ),
    ]
    updated, was_cleared = apply_clear_hook_suffix(hooks, "pytest tests")
    assert was_cleared is True
    assert updated[0].status_lines is not None
    assert updated[0].status_lines[0].suffix == "suffix_to_keep"
    assert updated[1].status_lines is not None
    assert updated[1].status_lines[0].suffix is None


# Tests for is_proposal_entry
# Tests for _is_test_target_hook
def test_is_test_target_hook_true() -> None:
    """Test that bb_rabbit_test commands are identified as test target hooks."""
    from sase.ace.hooks.test_targets import _is_test_target_hook

    hook = HookEntry(command="bb_rabbit_test //foo:test")
    assert _is_test_target_hook(hook) is True


def test_is_test_target_hook_false() -> None:
    """Test that non-test commands are not identified as test target hooks."""
    from sase.ace.hooks.test_targets import _is_test_target_hook

    hook = HookEntry(command="flake8 src")
    assert _is_test_target_hook(hook) is False

    hook2 = HookEntry(command="pytest tests")
    assert _is_test_target_hook(hook2) is False


# Tests for _create_test_target_hook
def test_create_test_target_hook() -> None:
    """Test creating a test target hook from a target string."""
    from sase.ace.hooks.test_targets import _create_test_target_hook

    hook = _create_test_target_hook("//foo/bar:test")
    assert hook.command == "bb_rabbit_test //foo/bar:test"
    assert hook.status_lines is None


# Tests for _hook_has_fix_excluded_suffix
def test_hook_has_fix_excluded_suffix_false_no_status_lines() -> None:
    """Test that hooks with no status_lines are not excluded."""
    from sase.ace.hooks.workflow_queries import _hook_has_fix_excluded_suffix

    hook = HookEntry(command="flake8 src")
    assert _hook_has_fix_excluded_suffix(hook) is False
