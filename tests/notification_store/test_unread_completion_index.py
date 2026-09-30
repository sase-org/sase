"""Parity between the Rust lean unread index and the Python projection."""

from pathlib import Path

from sase.ace.tui.actions.agents._notification_utils import (
    unread_completion_index_rows_from_notifications,
)
from sase.notifications import (
    ack_agent_completions,
    read_unread_completion_index,
)
from sase.notifications.store import (
    append_notification,
    read_notification_snapshot,
)

from .helpers import make_notification


def _completion(
    *,
    id: str,
    cl_name: str,
    raw_suffix: str | None = None,
    read: bool = False,
    dismissed: bool = False,
):
    action_data = {"cl_name": cl_name}
    if raw_suffix is not None:
        action_data["raw_suffix"] = raw_suffix
    return make_notification(
        id=id,
        sender="user-agent",
        action="JumpToAgent",
        action_data=action_data,
        read=read,
        dismissed=dismissed,
    )


def _settlement(
    *,
    id: str,
    sender: str = "epic-launch",
    cl_name: str = "proj",
    raw_suffix: str | None = "20260501010203",
    read: bool = False,
    dismissed: bool = False,
):
    action_data = {"cl_name": cl_name}
    if raw_suffix is not None:
        action_data["raw_suffix"] = raw_suffix
    return make_notification(
        id=id,
        sender=sender,
        action=None,
        action_data=action_data,
        read=read,
        dismissed=dismissed,
    )


def _row_tuple(row) -> tuple:
    return (row.id, row.cl_name, row.raw_suffix, row.read, row.dismissed)


def test_rust_index_matches_python_projection(temp_notifications_dir: Path) -> None:
    """The Rust index and the Python projection agree on ids, keys, flags."""
    append_notification(
        _completion(id="completion-exact", cl_name="proj", raw_suffix="20260501010203")
    )
    append_notification(_completion(id="completion-no-suffix", cl_name="proj"))
    append_notification(
        _settlement(
            id="settlement-dismissed",
            cl_name="proj",
            raw_suffix="20260501010203",
            read=True,
            dismissed=True,
        )
    )
    append_notification(
        _settlement(
            id="settlement-other",
            sender="monitor-settlement",
            cl_name="elsewhere",
            raw_suffix="20260501010203",
        )
    )
    append_notification(
        make_notification(
            id="unrelated",
            sender="remote-attention",
            action="JumpToAgent",
            action_data={"cl_name": "proj", "raw_suffix": "20260501010203"},
        )
    )
    append_notification(
        make_notification(
            id="gate",
            sender="user-agent",
            action="PlanApproval",
            action_data={"agent_cl_name": "proj"},
        )
    )

    snapshot = read_notification_snapshot(include_dismissed=True)
    rust_index = read_unread_completion_index()
    python_rows = unread_completion_index_rows_from_notifications(
        snapshot.notifications
    )

    assert rust_index.generation == snapshot.generation
    assert [_row_tuple(row) for row in rust_index.rows] == [
        _row_tuple(row) for row in python_rows
    ]
    assert [row.id for row in rust_index.rows] == [
        "completion-exact",
        "completion-no-suffix",
        "settlement-dismissed",
        "settlement-other",
    ]
    assert ("proj", None) in {(row.cl_name, row.raw_suffix) for row in rust_index.rows}


def test_ack_updates_index_flags_and_generation(temp_notifications_dir: Path) -> None:
    """An ack dismisses through the index with a bumped generation."""
    append_notification(
        _completion(id="completion-exact", cl_name="proj", raw_suffix="20260501010203")
    )
    append_notification(
        _settlement(id="settlement-exact", cl_name="proj", raw_suffix="20260501010203")
    )

    before = read_unread_completion_index()
    outcome = ack_agent_completions(
        [{"cl_name": "proj", "raw_suffix": "20260501010203"}]
    )

    assert outcome.dismissed_ids == ["completion-exact", "settlement-exact"]
    assert outcome.generation == before.generation + 1

    after = read_unread_completion_index()
    assert after.generation == outcome.generation
    assert {row.id for row in after.rows} == {
        "completion-exact",
        "settlement-exact",
    }
    assert all(row.dismissed for row in after.rows)

    snapshot = read_notification_snapshot(include_dismissed=True)
    python_rows = unread_completion_index_rows_from_notifications(
        snapshot.notifications
    )
    assert [_row_tuple(row) for row in after.rows] == [
        _row_tuple(row) for row in python_rows
    ]
