"""Tests for the mentor_checks module."""

from sase.ace.changespec import (
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
)
from sase.ace.scheduler.mentor_checks import (
    _all_non_skip_hooks_ready,
    _get_started_mentors_for_entry,
)
from test_utils import build_changespec


# Tests for _get_started_mentors_for_entry


def test_get_started_mentors_empty_mentors() -> None:
    """Test with empty MENTORS list returns empty set."""
    cs = build_changespec(mentors=[])
    assert _get_started_mentors_for_entry(cs, "1") == set()


def test_get_started_mentors_different_entry_id() -> None:
    """Test that only mentors for the specified entry_id are returned."""
    cs = build_changespec(
        mentors=[
            MentorEntry(
                entry_id="1",
                profiles=["code"],
                status_lines=[
                    MentorStatusLine(
                        timestamp="251231_120000",
                        profile_name="code",
                        mentor_name="dead_code",
                        status="PASSED",
                    )
                ],
            )
        ]
    )
    # Asking for entry_id "2" should return empty set
    assert _get_started_mentors_for_entry(cs, "2") == set()


def test_get_started_mentors_multiple() -> None:
    """Test with multiple started mentors from same profile."""
    cs = build_changespec(
        mentors=[
            MentorEntry(
                entry_id="1",
                profiles=["code"],
                status_lines=[
                    MentorStatusLine(
                        timestamp="251231_120000",
                        profile_name="code",
                        mentor_name="dead_code",
                        status="PASSED",
                    ),
                    MentorStatusLine(
                        timestamp="251231_120000",
                        profile_name="code",
                        mentor_name="shared_code",
                        status="RUNNING",
                    ),
                ],
            )
        ]
    )
    assert _get_started_mentors_for_entry(cs, "1") == {
        ("code", "dead_code"),
        ("code", "shared_code"),
    }


# Tests for _all_non_skip_hooks_ready


def _make_hook(
    command: str,
    entry_id: str,
    status: str,
    suffix: str | None = None,
    suffix_type: str | None = None,
) -> HookEntry:
    """Helper to create a HookEntry with a status line."""
    return HookEntry(
        command=command,
        status_lines=[
            HookStatusLine(
                commit_entry_num=entry_id,
                timestamp="251230_120000",
                status=status,
                duration="1m0s" if status in ("PASSED", "FAILED") else None,
                suffix=suffix,
                suffix_type=suffix_type,
                summary=None,
            )
        ],
    )


def test_all_non_skip_hooks_ready_empty_hooks() -> None:
    """Test that empty hooks list blocks mentors (hooks not yet added)."""
    cs = build_changespec(hooks=[])
    assert _all_non_skip_hooks_ready(cs, "1") is False


def test_all_non_skip_hooks_ready_hook_running() -> None:
    """Test mentors blocked when hook is RUNNING for latest entry."""
    cs = build_changespec(
        hooks=[
            _make_hook("make test", "1", "RUNNING"),
        ]
    )
    assert _all_non_skip_hooks_ready(cs, "1") is False


def test_all_non_skip_hooks_ready_failed_with_plain_entry_id() -> None:
    """Test mentors allowed when FAILED hook has plain entry ID suffix."""
    cs = build_changespec(
        hooks=[
            _make_hook("make test", "1", "FAILED", suffix="2"),
        ]
    )
    assert _all_non_skip_hooks_ready(cs, "1") is True


def test_all_non_skip_hooks_ready_failed_with_running_agent() -> None:
    """Test mentors allowed when FAILED hook has running_agent suffix_type."""
    cs = build_changespec(
        hooks=[
            _make_hook(
                "make test",
                "1",
                "FAILED",
                suffix="fix_hook-12345-251230_120000",
                suffix_type="running_agent",
            ),
        ]
    )
    assert _all_non_skip_hooks_ready(cs, "1") is True


def test_all_non_skip_hooks_ready_only_skip_hooks() -> None:
    """Test only !-prefixed hooks blocks mentors (non-! hooks not yet added)."""
    cs = build_changespec(
        hooks=[
            _make_hook("!$sase_hg_presubmit", "1", "PASSED"),
        ]
    )
    # Only skip hooks exist, so non-skip hooks haven't been added yet
    assert _all_non_skip_hooks_ready(cs, "1") is False


def test_all_non_skip_hooks_ready_status_for_different_entry() -> None:
    """Test hook that only has status for a different entry blocks mentors."""
    cs = build_changespec(
        hooks=[
            _make_hook("make test", "1", "PASSED"),  # Passed on entry 1
        ]
    )
    # Checking entry 2 - hook has no status for entry 2
    assert _all_non_skip_hooks_ready(cs, "2") is False


def test_all_non_skip_hooks_ready_one_blocking() -> None:
    """Test that one non-ready hook blocks mentors."""
    cs = build_changespec(
        hooks=[
            _make_hook("make test", "1", "PASSED"),
            _make_hook("make lint", "1", "FAILED", suffix=None),  # No proposal yet
        ]
    )
    assert _all_non_skip_hooks_ready(cs, "1") is False
