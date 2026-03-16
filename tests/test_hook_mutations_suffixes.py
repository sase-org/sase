"""Tests for ace/hooks/mutations.py - pure suffix operations."""

from sase.ace.changespec.models import HookEntry, HookStatusLine
from sase.ace.hooks.mutations import (
    _apply_clear_hook_suffix,
    _apply_hook_suffix_update,
    get_failed_hooks_file_path,
)


def _make_cs_with_hooks(hooks: list[HookEntry] | None = None):
    """Build a minimal ChangeSpec-like object for get_failed_hooks_file_path."""
    from sase.ace.changespec.models import ChangeSpec

    return ChangeSpec(
        name="test",
        description="desc",
        parent=None,
        cl=None,
        status="Draft",
        test_targets=None,
        kickstart=None,
        file_path="/tmp/test.gp",
        line_number=1,
        hooks=hooks,
    )


# ---------------------------------------------------------------------------
# _apply_hook_suffix_update
# ---------------------------------------------------------------------------


def test_apply_suffix_update_sets_suffix() -> None:
    sl = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_120000",
        status="FAILED",
    )
    hook = HookEntry(command="lint", status_lines=[sl])
    updated, was_updated = _apply_hook_suffix_update(
        [hook], "lint", "ZOMBIE", suffix_type="error"
    )
    assert was_updated is True
    assert updated[0].status_lines[0].suffix == "ZOMBIE"
    assert updated[0].status_lines[0].suffix_type == "error"


def test_apply_suffix_update_wrong_command() -> None:
    sl = HookStatusLine(
        commit_entry_num="1", timestamp="260101_120000", status="FAILED"
    )
    hook = HookEntry(command="test", status_lines=[sl])
    updated, was_updated = _apply_hook_suffix_update([hook], "lint", "ZOMBIE")
    assert was_updated is False
    assert updated[0].status_lines[0].suffix is None


def test_apply_suffix_update_no_status_lines() -> None:
    hook = HookEntry(command="lint", status_lines=None)
    updated, was_updated = _apply_hook_suffix_update([hook], "lint", "ZOMBIE")
    assert was_updated is False


def test_apply_suffix_update_with_entry_id() -> None:
    sl1 = HookStatusLine(
        commit_entry_num="1", timestamp="260101_110000", status="PASSED"
    )
    sl2 = HookStatusLine(
        commit_entry_num="2", timestamp="260101_120000", status="FAILED"
    )
    hook = HookEntry(command="lint", status_lines=[sl1, sl2])
    updated, was_updated = _apply_hook_suffix_update(
        [hook],
        "lint",
        "fix-99-260101_130000",
        entry_id="2",
        suffix_type="running_agent",
    )
    assert was_updated is True
    # sl2 should have the suffix, sl1 should not
    assert updated[0].status_lines[0].suffix is None
    assert updated[0].status_lines[1].suffix == "fix-99-260101_130000"


def test_apply_suffix_update_with_summary() -> None:
    sl = HookStatusLine(
        commit_entry_num="1", timestamp="260101_120000", status="FAILED"
    )
    hook = HookEntry(command="lint", status_lines=[sl])
    updated, was_updated = _apply_hook_suffix_update(
        [hook],
        "lint",
        "fix-99-260101_130000",
        suffix_type="running_agent",
        summary="Type error in main.py",
    )
    assert was_updated is True
    assert updated[0].status_lines[0].summary == "Type error in main.py"


def test_apply_suffix_update_multiple_hooks() -> None:
    sl1 = HookStatusLine(
        commit_entry_num="1", timestamp="260101_110000", status="PASSED"
    )
    sl2 = HookStatusLine(
        commit_entry_num="1", timestamp="260101_120000", status="FAILED"
    )
    hook1 = HookEntry(command="lint", status_lines=[sl1])
    hook2 = HookEntry(command="test", status_lines=[sl2])
    updated, was_updated = _apply_hook_suffix_update(
        [hook1, hook2], "test", "ZOMBIE", suffix_type="error"
    )
    assert was_updated is True
    assert updated[0].status_lines[0].suffix is None  # lint unchanged
    assert updated[1].status_lines[0].suffix == "ZOMBIE"  # test updated


# ---------------------------------------------------------------------------
# _apply_clear_hook_suffix
# ---------------------------------------------------------------------------


def test_apply_clear_suffix() -> None:
    sl = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_120000",
        status="FAILED",
        suffix="ZOMBIE",
        suffix_type="error",
    )
    hook = HookEntry(command="lint", status_lines=[sl])
    updated, was_cleared = _apply_clear_hook_suffix([hook], "lint")
    assert was_cleared is True
    assert updated[0].status_lines[0].suffix is None


def test_apply_clear_suffix_no_suffix() -> None:
    sl = HookStatusLine(
        commit_entry_num="1", timestamp="260101_120000", status="PASSED"
    )
    hook = HookEntry(command="lint", status_lines=[sl])
    updated, was_cleared = _apply_clear_hook_suffix([hook], "lint")
    assert was_cleared is False


def test_apply_clear_suffix_wrong_command() -> None:
    sl = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_120000",
        status="FAILED",
        suffix="ZOMBIE",
    )
    hook = HookEntry(command="test", status_lines=[sl])
    updated, was_cleared = _apply_clear_hook_suffix([hook], "lint")
    assert was_cleared is False
    assert updated[0].status_lines[0].suffix == "ZOMBIE"


def test_apply_clear_suffix_no_status_lines() -> None:
    hook = HookEntry(command="lint", status_lines=None)
    updated, was_cleared = _apply_clear_hook_suffix([hook], "lint")
    assert was_cleared is False


def test_apply_clear_suffix_clears_latest_only() -> None:
    sl1 = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_110000",
        status="PASSED",
        suffix="old_suffix",
    )
    sl2 = HookStatusLine(
        commit_entry_num="2",
        timestamp="260101_120000",
        status="FAILED",
        suffix="ZOMBIE",
    )
    hook = HookEntry(command="lint", status_lines=[sl1, sl2])
    updated, was_cleared = _apply_clear_hook_suffix([hook], "lint")
    assert was_cleared is True
    # Only the latest (entry 2) should be cleared
    assert updated[0].status_lines[0].suffix == "old_suffix"
    assert updated[0].status_lines[1].suffix is None


# ---------------------------------------------------------------------------
# get_failed_hooks_file_path
# ---------------------------------------------------------------------------


def test_get_failed_hooks_file_path_in_suffix() -> None:
    sl = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_120000",
        status="PASSED",
        suffix="/tmp/abc_failed_hooks_xyz.txt",
        suffix_type="metahook_complete",
    )
    hook = HookEntry(command="meta", status_lines=[sl])
    cs = _make_cs_with_hooks([hook])
    result = get_failed_hooks_file_path(cs)
    assert result == "/tmp/abc_failed_hooks_xyz.txt"


def test_get_failed_hooks_file_path_in_summary() -> None:
    sl = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_120000",
        status="PASSED",
        summary="Results: /tmp/test_failed_hooks_run1.txt",
    )
    hook = HookEntry(command="meta", status_lines=[sl])
    cs = _make_cs_with_hooks([hook])
    result = get_failed_hooks_file_path(cs)
    assert result == "/tmp/test_failed_hooks_run1.txt"


def test_get_failed_hooks_file_path_none() -> None:
    sl = HookStatusLine(
        commit_entry_num="1",
        timestamp="260101_120000",
        status="PASSED",
    )
    hook = HookEntry(command="lint", status_lines=[sl])
    cs = _make_cs_with_hooks([hook])
    assert get_failed_hooks_file_path(cs) is None


def test_get_failed_hooks_file_path_no_hooks() -> None:
    cs = _make_cs_with_hooks(None)
    assert get_failed_hooks_file_path(cs) is None


def test_get_failed_hooks_file_path_no_status_lines() -> None:
    hook = HookEntry(command="lint", status_lines=None)
    cs = _make_cs_with_hooks([hook])
    assert get_failed_hooks_file_path(cs) is None
