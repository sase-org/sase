"""Ack-pipeline tests (epic sase-1d7 phase core-unread-ack-index).

Completion never reads the store on the UI thread, cache removal is by
the Rust-returned id set, and rapid acks coalesce into one Rust call per
batch.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from sase.ace.tui.actions.agents._unread_state import _UnreadNotificationDismissal

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


class _DeferredAckApp(UnreadJumpApp):
    """UnreadJumpApp with a deferred ack worker (coalescing observable)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.worker_calls: list[Callable[[], None]] = []
        self.thread_calls: list[Callable[[], None]] = []
        self.notifications: list[tuple[str, str | None]] = []
        self._notification_snapshot_cache = None
        self._pending_ack_op_seq = 0
        self._pending_ack_overlay: dict[Any, Any] = {}

    def run_worker(self, work: Callable[[], None], **_kwargs: object) -> object:
        self.worker_calls.append(work)
        return object()

    def call_from_thread(self, callback: Callable[[], None]) -> None:
        self.thread_calls.append(callback)
        callback()

    def notify(self, message: str, **kwargs: object) -> None:
        self.notifications.append((message, kwargs.get("severity")))


def _completion_notification(agent: Any, *, notification_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=notification_id,
        sender="user-agent",
        action="JumpToAgent",
        action_data={
            "cl_name": agent.cl_name,
            "raw_suffix": agent.raw_suffix or "",
        },
        dismissed=False,
    )


def test_ack_completion_never_reads_store_on_ui_thread(
    ack_completions: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Completion schedules only the guarded async resync, never a sync read."""
    agent = make_agent(status="DONE")
    app = _DeferredAckApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._notification_snapshot_cache = SimpleNamespace(
        notifications=[_completion_notification(agent, notification_id="n-agent")]
    )
    ack_completions.return_value = SimpleNamespace(
        dismissed_ids={"n-agent"}, generation=7
    )

    sync_reads: list[str] = []
    monkeypatch.setattr(
        app,
        "_read_notification_snapshot_from_provider",
        lambda *args, **kwargs: (
            sync_reads.append("read") or SimpleNamespace(notifications=[])
        ),
    )

    assert app._acknowledge_agent_unread(agent)
    assert app.notification_count_refresh_calls == 0
    assert sync_reads == []

    assert len(app.worker_calls) == 1
    app.worker_calls[0]()

    ack_completions.assert_called_once()
    assert sync_reads == []
    assert app.notification_count_refresh_calls == 0
    assert app.scheduled_notification_resync_calls == 1
    assert app._notification_snapshot_cache.notifications == []
    assert app._pending_ack_overlay[agent.identity] == (1, 7)
    assert threading.current_thread() is threading.main_thread()


def test_five_rapid_acks_coalesce_into_one_write(
    ack_completions: Mock,
) -> None:
    """Five acks queued before the drain runs issue one Rust call."""
    agents = [
        make_agent(name=f"node-{i}", status="DONE", raw_suffix=f"rapid-{i}")
        for i in range(5)
    ]
    app = _DeferredAckApp(agents)
    for agent in agents:
        app._unread_completed_agent_ids.add(agent.identity)
    ack_completions.return_value = SimpleNamespace(
        dismissed_ids={f"n-rapid-{i}" for i in range(5)}, generation=7
    )

    for agent in agents:
        assert app._acknowledge_agent_unread(agent)

    assert app._unread_completed_agent_ids == set()
    # One drain scheduled for the whole burst, not one worker per ack.
    assert len(app.worker_calls) == 1

    for work in list(app.worker_calls):
        work()

    assert ack_completions.call_count == 1
    assert app.notification_count_refresh_calls == 0
    assert app.scheduled_notification_resync_calls == 5


def test_failed_batch_restores_only_owned_identities(
    ack_completions: Mock,
) -> None:
    """Each op in a failed batch restores only its still-owned identities."""
    agent = make_agent(status="DONE")
    app = _DeferredAckApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    from sase.ace.tui.actions.agents._pending_ack_fence import register_pending_ack

    keys = tuple(app._notification_keys_for_agents([agent]))
    op1 = register_pending_ack(app, {agent.identity})
    req1 = _UnreadNotificationDismissal(
        agents=(agent,),
        keys=keys,
        identities=frozenset({agent.identity}),
        restore_manual_ids=frozenset(),
        prior_pending_bulk_read_ids=None,
    )
    object.__setattr__(req1, "op_id", op1)
    # A later op on the same identity takes ownership from the first.
    op2 = register_pending_ack(app, {agent.identity})
    req2 = _UnreadNotificationDismissal(
        agents=(agent,),
        keys=keys,
        identities=frozenset({agent.identity}),
        restore_manual_ids=frozenset(),
        prior_pending_bulk_read_ids=None,
    )
    object.__setattr__(req2, "op_id", op2)

    app._unread_completed_agent_ids.discard(agent.identity)

    from sase.ace.tui.actions.agents import _unread_ack_writer as writer

    writer.enqueue_unread_ack(app, req1)
    writer.enqueue_unread_ack(app, req2)
    assert len(app.worker_calls) == 1

    ack_completions.side_effect = RuntimeError("store unavailable")
    for work in list(app.worker_calls):
        work()

    assert ack_completions.call_count == 1
    # The first op owned nothing at failure time; only the second op's
    # identity restores, once.
    assert app._unread_completed_agent_ids == {agent.identity}
    assert len(app.notifications) == 2


def test_cache_removal_is_by_returned_ids_not_keys_scan() -> None:
    """Completion drops exactly the Rust-returned ids, nothing more."""
    agent = make_agent(status="DONE")
    app = _DeferredAckApp([agent])
    first = _completion_notification(agent, notification_id="n-first")
    second = _completion_notification(agent, notification_id="n-second")
    app._notification_snapshot_cache = SimpleNamespace(notifications=[first, second])
    app._last_unread_ids = {"n-first", "n-second"}

    request = _UnreadNotificationDismissal(
        agents=(agent,),
        keys=tuple(app._notification_keys_for_agents([agent])),
        identities=frozenset({agent.identity}),
        restore_manual_ids=frozenset(),
        prior_pending_bulk_read_ids=None,
    )
    # Both rows match the same key; the ack names only one id, and an id
    # the ack did not return stays cached.
    app._complete_unread_notification_dismissal(
        request,
        dismissed_count=1,
        error=None,
        store_bytes=None,
        matched_ids={"n-first", "n-gone"},
        generation=7,
    )

    assert [n.id for n in app._notification_snapshot_cache.notifications] == [
        "n-second"
    ]
    assert app._last_unread_ids == {"n-second"}
    assert app.notification_count_refresh_calls == 0
    assert app.scheduled_notification_resync_calls == 1
