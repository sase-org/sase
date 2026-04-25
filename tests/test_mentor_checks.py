"""Tests for the mentor_checks module."""

import os
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from sase.ace.changespec import (
    CommitEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
)
from sase.ace.scheduler.mentor_checks import (
    _all_non_skip_hooks_ready,
    _check_mentor_completion_notifications,
    _get_started_mentors_for_entry,
)
from sase.notifications import load_notifications
from sase.notifications.mentor_completion_marker import is_notified
from test_utils import build_changespec


@pytest.fixture()
def isolated_notifications_store() -> Iterator[None]:
    """Re-point notification storage at the conftest-redirected ~/.sase.

    The store module resolves ``NOTIFICATIONS_DIR`` at import time via
    ``os.path.expanduser``, which runs before the conftest redirect, so
    writes leak to the real home. This fixture re-resolves both constants
    against the now-patched expanduser.
    """
    notifications_dir = os.path.expanduser("~/.sase/notifications")
    notifications_file = os.path.join(notifications_dir, "notifications.jsonl")
    with (
        patch("sase.notifications.store.NOTIFICATIONS_DIR", notifications_dir),
        patch("sase.notifications.store.NOTIFICATIONS_FILE", notifications_file),
    ):
        yield


def _noop_log(_msg: str, _color: str | None = None) -> None:
    return None


def _make_status_line(
    profile: str, mentor: str, status: str, suffix: str | None = None
) -> MentorStatusLine:
    return MentorStatusLine(
        profile_name=profile,
        mentor_name=mentor,
        status=status,
        timestamp="251231_120000",
        duration="0h2m15s" if status not in ("RUNNING",) else None,
        suffix=suffix,
        suffix_type="running_agent" if status == "RUNNING" else "plain",
    )


def _commit(num: int) -> CommitEntry:
    return CommitEntry(number=num, note=f"commit {num}")


def _hook_passed(entry_id: str) -> HookEntry:
    return HookEntry(
        command="make test",
        status_lines=[
            HookStatusLine(
                commit_entry_num=entry_id,
                timestamp="251230_120000",
                status="PASSED",
                duration="1m0s",
            )
        ],
    )


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


# Tests for _check_mentor_completion_notifications


def test_completion_notify_all_terminal_fires_once(
    isolated_notifications_store: None,
) -> None:
    del isolated_notifications_store
    """All mentor status_lines terminal -> one notification, no re-fire."""
    cs = build_changespec(
        file_path="/proj.gp",
        name="cl-1",
        commits=[_commit(1)],
        hooks=[_hook_passed("1")],
        mentors=[
            MentorEntry(
                entry_id="1",
                profiles=["code"],
                status_lines=[
                    _make_status_line("code", "dead_code", "PASSED"),
                    _make_status_line("code", "shared_code", "COMMENTED"),
                ],
            )
        ],
    )

    updates = _check_mentor_completion_notifications(cs, _noop_log)
    assert len(updates) == 1
    notes = load_notifications()
    assert len(notes) == 1
    assert notes[0].action == "JumpToMentorReview"
    assert notes[0].action_data["entry_id"] == "1"
    assert notes[0].action_data["changespec_name"] == "cl-1"
    assert is_notified("/proj.gp", "cl-1", "1") is True

    # Re-running should not fire another notification.
    updates2 = _check_mentor_completion_notifications(cs, _noop_log)
    assert updates2 == []
    assert len(load_notifications()) == 1


def test_completion_notify_no_profiles_matched_fires_once(
    isolated_notifications_store: None,
) -> None:
    del isolated_notifications_store
    """Hooks ready and no MentorEntry exists -> no-match notification."""
    cs = build_changespec(
        file_path="/proj.gp",
        name="cl-1",
        commits=[_commit(1)],
        hooks=[_hook_passed("1")],
        mentors=None,
    )

    updates = _check_mentor_completion_notifications(cs, _noop_log)
    assert len(updates) == 1
    notes = load_notifications()
    assert len(notes) == 1
    assert any("no mentor profiles matched" in note for note in notes[0].notes)
    assert is_notified("/proj.gp", "cl-1", "1") is True

    # Idempotent: second call must not re-fire.
    updates2 = _check_mentor_completion_notifications(cs, _noop_log)
    assert updates2 == []
    assert len(load_notifications()) == 1


def test_completion_notify_no_match_skipped_when_hooks_not_ready(
    isolated_notifications_store: None,
) -> None:
    del isolated_notifications_store
    """No MentorEntry but hooks not ready -> no notification yet."""
    cs = build_changespec(
        file_path="/proj.gp",
        name="cl-1",
        commits=[_commit(1)],
        hooks=[
            HookEntry(
                command="make test",
                status_lines=[
                    HookStatusLine(
                        commit_entry_num="1",
                        timestamp="251230_120000",
                        status="RUNNING",
                    )
                ],
            )
        ],
        mentors=None,
    )

    updates = _check_mentor_completion_notifications(cs, _noop_log)
    assert updates == []
    assert load_notifications() == []
    assert is_notified("/proj.gp", "cl-1", "1") is False


def test_completion_notify_skipped_while_mentors_running(
    isolated_notifications_store: None,
) -> None:
    del isolated_notifications_store
    """Some mentors still RUNNING -> no notification."""
    cs = build_changespec(
        file_path="/proj.gp",
        name="cl-1",
        commits=[_commit(1)],
        hooks=[_hook_passed("1")],
        mentors=[
            MentorEntry(
                entry_id="1",
                profiles=["code"],
                status_lines=[
                    _make_status_line("code", "dead_code", "PASSED"),
                    _make_status_line(
                        "code",
                        "shared_code",
                        "RUNNING",
                        suffix="mentor_x-12345-251231_120000",
                    ),
                ],
            )
        ],
    )

    updates = _check_mentor_completion_notifications(cs, _noop_log)
    assert updates == []
    assert load_notifications() == []
    assert is_notified("/proj.gp", "cl-1", "1") is False


def test_completion_notify_skipped_when_profiles_registered_but_not_started(
    isolated_notifications_store: None,
) -> None:
    del isolated_notifications_store
    """MentorEntry exists with profiles but no status_lines -> wait."""
    cs = build_changespec(
        file_path="/proj.gp",
        name="cl-1",
        commits=[_commit(1)],
        hooks=[_hook_passed("1")],
        mentors=[
            MentorEntry(
                entry_id="1",
                profiles=["code"],
                status_lines=None,
            )
        ],
    )

    updates = _check_mentor_completion_notifications(cs, _noop_log)
    assert updates == []
    assert load_notifications() == []


def test_completion_notify_summary_includes_commented_count(
    isolated_notifications_store: None,
) -> None:
    del isolated_notifications_store
    """COMMENTED count surfaces in the notification summary line."""
    cs = build_changespec(
        file_path="/proj.gp",
        name="cl-1",
        commits=[_commit(1)],
        hooks=[_hook_passed("1")],
        mentors=[
            MentorEntry(
                entry_id="1",
                profiles=["code"],
                status_lines=[
                    _make_status_line("code", "a", "PASSED"),
                    _make_status_line("code", "b", "COMMENTED"),
                    _make_status_line("code", "c", "COMMENTED"),
                ],
            )
        ],
    )

    _check_mentor_completion_notifications(cs, _noop_log)
    notes = load_notifications()
    assert len(notes) == 1
    summary_line = next(n for n in notes[0].notes if "mentors finished" in n)
    assert "3/3" in summary_line
    assert "(2 commented)" in summary_line
