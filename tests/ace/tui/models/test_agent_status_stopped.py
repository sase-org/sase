"""``STOPPED`` status semantics: terminal, dismissable, not failed/resumable.

``STOPPED`` marks a repeat-chain slot skipped by a predecessor's ``STOP``. It
is a finished, non-error row: it groups as Done (never Failed), is dismissable
like other terminal rows, but is neither resumable as a chat completion nor
revertable as a code-producing agent (it never executed).
"""

from __future__ import annotations

from sase.agent.status_buckets import _TERMINAL_STATUSES, status_bucket_for_values
from sase.ace.tui.models.agent_status import (
    DISMISSABLE_STATUSES,
    STOPPED_COLOR,
    STOPPED_GLYPH,
    STOPPED_STATUS,
    is_resumable_done_status,
    is_revertable_agent_status,
    is_unread_completed_status,
)


def test_stopped_is_terminal() -> None:
    assert STOPPED_STATUS in _TERMINAL_STATUSES


def test_stopped_groups_as_done_not_failed() -> None:
    assert status_bucket_for_values(STOPPED_STATUS) == "Done"
    assert status_bucket_for_values(STOPPED_STATUS) != "Failed"


def test_stopped_is_dismissable() -> None:
    assert STOPPED_STATUS in DISMISSABLE_STATUSES
    assert is_unread_completed_status(STOPPED_STATUS) is True


def test_stopped_is_not_resumable() -> None:
    assert is_resumable_done_status(STOPPED_STATUS) is False


def test_stopped_is_not_revertable() -> None:
    # Dismissable but not revertable: the skipped slot never ran, so it has no
    # commits to revert.
    assert is_revertable_agent_status(STOPPED_STATUS) is False


def test_stopped_visual_identity_constants() -> None:
    assert STOPPED_STATUS == "STOPPED"
    assert STOPPED_COLOR == "#8787AF"
    assert STOPPED_GLYPH == "Ø"
