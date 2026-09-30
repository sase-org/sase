"""Tests for the pending-ack fence (epic sase-1d7 phase pending-ack-fence)."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sase.ace.tui.actions.agents._loading_finalize import (
    _sync_unread_completed_agents,
)
from sase.ace.tui.actions.agents._pending_ack_fence import (
    pending_ack_identities,
    snapshot_read_seq,
    stamp_snapshot_read_seq,
)
from sase.notifications import Notification

from ._agent_unread_helpers import make_agent
from ._agent_unread_navigation_helpers import UnreadJumpApp


@pytest.fixture(autouse=True)
def notification_dismiss(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(return_value=1)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    return dismiss


def _completion_notification(agent, *, notification_id: str) -> Notification:
    return Notification(
        id=notification_id,
        timestamp="2026-08-16T12:00:00",
        sender="user-agent",
        action="JumpToAgent",
        action_data={
            "cl_name": agent.cl_name,
            "raw_suffix": agent.raw_suffix or "",
        },
    )


def _stamped_snapshot(notifications: list[Notification], seq: int) -> SimpleNamespace:
    return stamp_snapshot_read_seq(
        SimpleNamespace(notifications=list(notifications)),
        seq,
    )


class _FenceApp(UnreadJumpApp):
    """UnreadJumpApp with fence state, workers, and a snapshot cache."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.worker_calls: list[Callable[[], None]] = []
        self.notifications: list[tuple[str, str | None]] = []
        self._notification_snapshot_cache = None
        self._notification_snapshot_read_seq = None
        self._notification_snapshot_version = 0
        self._notif_read_seq = 0
        self._pending_ack_op_seq = 0
        self._pending_ack_overlay = {}

    def run_worker(self, work: Callable[[], None], **_kwargs: object) -> object:
        self.worker_calls.append(work)
        return object()

    def call_from_thread(self, callback: Callable[[], None]) -> None:
        callback()

    def notify(self, message: str, **kwargs: object) -> None:
        self.notifications.append((message, kwargs.get("severity")))


def _ack_both(app: _FenceApp) -> None:
    """Bulk-ack every unread row without running the store worker."""
    scheduled = len(app.worker_calls)
    result = app._toggle_all_unread_done_agents_read()
    assert result.count == 2
    assert len(app.worker_calls) == scheduled + 1


def test_pre_write_poll_snapshot_keeps_ack_cleared() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = _FenceApp([first, second])
    app._unread_completed_agent_ids.update({first.identity, second.identity})

    _ack_both(app)
    assert app._unread_completed_agent_ids == set()
    assert pending_ack_identities(app) == {first.identity, second.identity}

    # A poll applying a snapshot read that started before the write landed
    # still carries both active notifications; the fence holds them read.
    app._reconcile_unread_from_completion_notifications(
        [
            _completion_notification(first, notification_id="n-first"),
            _completion_notification(second, notification_id="n-second"),
        ],
        snapshot_seq=app._notif_read_seq,
    )

    assert app._unread_completed_agent_ids == set()


def test_pre_write_snapshot_through_finalize_keeps_ack_cleared() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = _FenceApp([first, second])
    app._unread_completed_agent_ids.update({first.identity, second.identity})

    _ack_both(app)

    app._notification_snapshot_cache = _stamped_snapshot(
        [
            _completion_notification(first, notification_id="n-first"),
            _completion_notification(second, notification_id="n-second"),
        ],
        app._notif_read_seq,
    )
    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_stale_snapshot_landing_after_fresh_is_ignored() -> None:
    agent = make_agent(status="DONE")
    app = _FenceApp([agent])

    fresh = _stamped_snapshot(
        [_completion_notification(agent, notification_id="n-fresh")], 5
    )
    assert app._set_notification_snapshot_cache(fresh) is True
    assert snapshot_read_seq(app._notification_snapshot_cache) == 5

    stale = _stamped_snapshot(
        [_completion_notification(agent, notification_id="n-stale")], 3
    )
    assert app._set_notification_snapshot_cache(stale) is False
    assert app._notification_snapshot_cache is fresh
    assert snapshot_read_seq(app._notification_snapshot_cache) == 5


def test_pending_entry_retires_only_after_post_write_read() -> None:
    agent = make_agent(status="DONE")
    app = _FenceApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    app._toggle_all_unread_done_agents_read()
    assert app._unread_completed_agent_ids == set()
    [work] = app.worker_calls
    work()
    done_seq = app._notif_read_seq
    assert app._pending_ack_overlay[agent.identity] == (1, done_seq)

    active = [_completion_notification(agent, notification_id="n-active")]

    # A snapshot from the same sequence did not begin after the write.
    app._reconcile_unread_from_completion_notifications(active, snapshot_seq=done_seq)
    assert app._unread_completed_agent_ids == set()
    assert pending_ack_identities(app) == {agent.identity}

    # The first read that began after the write retires the entry, so a
    # genuinely new completion resurfaces (at most one poll later).
    app._reconcile_unread_from_completion_notifications(
        active, snapshot_seq=done_seq + 1
    )
    assert app._unread_completed_agent_ids == {agent.identity}
    assert pending_ack_identities(app) == set()


def test_failed_write_restores_only_owned_identities(
    notification_dismiss: Mock,
) -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = _FenceApp([first, second])
    app._unread_completed_agent_ids.update({first.identity, second.identity})

    _ack_both(app)
    # Undo restores both rows and releases the first op's fence entries.
    assert app._toggle_all_unread_done_agents_read().count == 2
    assert app._unread_completed_agent_ids == {first.identity, second.identity}
    # A second bulk ack takes ownership of both identities.
    _ack_both(app)
    assert pending_ack_identities(app) == {first.identity, second.identity}

    notification_dismiss.side_effect = RuntimeError("store unavailable")
    app.worker_calls[0]()
    # The first op no longer owns anything: nothing restores, the second
    # op's bulk-undo snapshot is untouched, and no repaint runs for it.
    assert app._unread_completed_agent_ids == set()
    assert app._pending_bulk_read_agent_ids == {first.identity, second.identity}

    app.worker_calls[1]()
    assert app._unread_completed_agent_ids == {first.identity, second.identity}
    assert app._pending_bulk_read_agent_ids is None
    assert pending_ack_identities(app) == set()
    assert len(app.notifications) == 2


def test_reconfirmation_keeps_undo_armed_but_new_unread_invalidates() -> None:
    acked = make_agent(name="acked", status="DONE", raw_suffix="acked")
    fresh = make_agent(name="fresh", status="DONE", raw_suffix="fresh")
    app = _FenceApp([acked, fresh])
    app._unread_completed_agent_ids.add(acked.identity)

    app._toggle_all_unread_done_agents_read()
    app._pending_bulk_read_agent_ids = {acked.identity}

    # Re-confirming only the pending identity keeps undo armed.
    app._reconcile_unread_from_completion_notifications(
        [_completion_notification(acked, notification_id="n-acked")],
    )
    assert app._unread_completed_agent_ids == set()
    assert app._pending_bulk_read_agent_ids == {acked.identity}

    # A genuinely new unread identity still invalidates undo.
    app._reconcile_unread_from_completion_notifications(
        [_completion_notification(fresh, notification_id="n-fresh")],
    )
    assert app._unread_completed_agent_ids == {fresh.identity}
    assert app._pending_bulk_read_agent_ids is None
