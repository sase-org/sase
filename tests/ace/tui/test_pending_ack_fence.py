"""Tests for the generation-fenced pending-ack overlay (epic sase-1d7)."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sase.ace.tui.actions.agents._loading_finalize import (
    _sync_unread_completed_agents,
)
from sase.ace.tui.actions.agents._notification_utils import (
    unread_completion_index_rows_from_notifications as _rows,
)
from sase.ace.tui.actions.agents._pending_ack_fence import (
    pending_ack_identities,
    snapshot_generation,
)
from sase.notifications import Notification

from ._agent_unread_helpers import make_agent
from ._agent_unread_navigation_helpers import UnreadJumpApp


@pytest.fixture(autouse=True)
def ack_completions(monkeypatch: pytest.MonkeyPatch) -> Mock:
    ack = Mock(return_value=SimpleNamespace(dismissed_ids=set(), generation=7))
    monkeypatch.setattr(
        "sase.notifications.ack_agent_completions",
        ack,
    )
    return ack


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


def _generation_snapshot(
    notifications: list[Notification], generation: int
) -> SimpleNamespace:
    return SimpleNamespace(notifications=list(notifications), generation=generation)


class _FenceApp(UnreadJumpApp):
    """UnreadJumpApp with fence state, workers, and a snapshot cache."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.worker_calls: list[Callable[[], None]] = []
        self.notifications: list[tuple[str, str | None]] = []
        self._notification_snapshot_cache = None
        self._notification_snapshot_generation = None
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
    # Coalescing writer: a second ack while a drain is pending joins the
    # same batch instead of scheduling a second worker.
    assert len(app.worker_calls) in (scheduled, scheduled + 1)


def test_pre_write_poll_snapshot_keeps_ack_cleared() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = _FenceApp([first, second])
    app._unread_completed_agent_ids.update({first.identity, second.identity})

    _ack_both(app)
    assert app._unread_completed_agent_ids == set()
    assert pending_ack_identities(app) == {first.identity, second.identity}

    # The worker has not finished, so done_generation is None: applying an
    # observation at any generation still carries both active rows, and
    # the fence holds them read.
    rows = _rows(
        [
            _completion_notification(first, notification_id="n-first"),
            _completion_notification(second, notification_id="n-second"),
        ]
    )
    app._reconcile_unread_from_completion_notifications(rows, applied_generation=7)
    assert app._unread_completed_agent_ids == set()

    app._reconcile_unread_from_completion_notifications(rows, applied_generation=None)
    assert app._unread_completed_agent_ids == set()


def test_pre_write_snapshot_through_finalize_keeps_ack_cleared() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = _FenceApp([first, second])
    app._unread_completed_agent_ids.update({first.identity, second.identity})

    _ack_both(app)

    app._notification_snapshot_cache = _generation_snapshot(
        [
            _completion_notification(first, notification_id="n-first"),
            _completion_notification(second, notification_id="n-second"),
        ],
        7,
    )
    _sync_unread_completed_agents(app, on_agents_tab=True)  # type: ignore[arg-type]

    assert app._unread_completed_agent_ids == set()


def test_stale_snapshot_landing_after_fresh_is_ignored() -> None:
    agent = make_agent(status="DONE")
    app = _FenceApp([agent])

    fresh = _generation_snapshot(
        [_completion_notification(agent, notification_id="n-fresh")], 5
    )
    assert app._set_notification_snapshot_cache(fresh) is True
    assert snapshot_generation(app._notification_snapshot_cache) == 5

    stale = _generation_snapshot(
        [_completion_notification(agent, notification_id="n-stale")], 3
    )
    assert app._set_notification_snapshot_cache(stale) is False
    assert app._notification_snapshot_cache is fresh
    assert snapshot_generation(app._notification_snapshot_cache) == 5


def test_snapshot_without_generation_inherits_cached_and_is_accepted() -> None:
    agent = make_agent(status="DONE")
    app = _FenceApp([agent])

    fresh = _generation_snapshot(
        [_completion_notification(agent, notification_id="n-fresh")], 5
    )
    assert app._set_notification_snapshot_cache(fresh) is True

    derived = SimpleNamespace(
        notifications=[_completion_notification(agent, notification_id="n-derived")]
    )
    assert app._set_notification_snapshot_cache(derived) is True
    assert app._notification_snapshot_cache is derived
    assert app._notification_snapshot_generation == 5


def test_pending_entry_retires_only_after_post_write_observation() -> None:
    agent = make_agent(status="DONE")
    app = _FenceApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    app._toggle_all_unread_done_agents_read()
    assert app._unread_completed_agent_ids == set()
    [work] = app.worker_calls
    work()
    assert app._pending_ack_overlay[agent.identity] == (1, 7)

    rows = _rows([_completion_notification(agent, notification_id="n-active")])

    # An observation one generation before the ack's write keeps the
    # overlay and does not resurrect the row.
    app._reconcile_unread_from_completion_notifications(rows, applied_generation=6)
    assert app._unread_completed_agent_ids == set()
    assert pending_ack_identities(app) == {agent.identity}

    # An observation at the ack's own generation retires the entry, so a
    # still-active row may become unread again.
    app._reconcile_unread_from_completion_notifications(rows, applied_generation=7)
    assert app._unread_completed_agent_ids == {agent.identity}
    assert pending_ack_identities(app) == set()


def test_failed_write_restores_only_owned_identities(
    ack_completions: Mock,
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

    ack_completions.side_effect = RuntimeError("store unavailable")
    # Coalescing writer: both ops drain in one batch with one Rust call.
    # The first op no longer owns anything so only the second op's
    # identities restore; each failed op still reports its own error.
    assert len(app.worker_calls) >= 1
    for work in list(app.worker_calls):
        work()
    assert ack_completions.call_count == 1
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
        _rows([_completion_notification(acked, notification_id="n-acked")]),
    )
    assert app._unread_completed_agent_ids == set()
    assert app._pending_bulk_read_agent_ids == {acked.identity}

    # A genuinely new unread identity still invalidates undo.
    app._reconcile_unread_from_completion_notifications(
        _rows([_completion_notification(fresh, notification_id="n-fresh")]),
    )
    assert app._unread_completed_agent_ids == {fresh.identity}
    assert app._pending_bulk_read_agent_ids is None


def test_ack_completion_records_returned_generation(
    ack_completions: Mock,
) -> None:
    """The drain records the ack's generation, not a read sequence."""
    agent = make_agent(status="DONE")
    app = _FenceApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    ack_completions.return_value = SimpleNamespace(
        dismissed_ids={"n-active"}, generation=9
    )

    app._toggle_all_unread_done_agents_read()
    [work] = app.worker_calls
    work()

    assert app._pending_ack_overlay[agent.identity] == (1, 9)
    assert ack_completions.call_count == 1
    assert app.scheduled_notification_resync_calls == 1
