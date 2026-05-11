"""Phase 2 wiring tests for Agents-tab completion-notification dismissal.

Exercises the ``AgentNotificationMixin`` helpers
``_dismiss_agent_completion_notifications_for_agents_tab`` and
``_request_agent_completion_dismiss`` plus the latch arming inside
``_poll_agent_completions`` and the trigger from
``EventHandlersMixin._record_user_activity``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.agents._notifications import (
    AgentNotificationMixin,
    _is_agent_completion_notification,
)
from sase.notifications.models import Notification


def _make_completion(
    *, action: str = "JumpToAgent", cl_name: str = "demo", n_id: str = "n1"
) -> Notification:
    return Notification(
        id=n_id,
        timestamp="2026-05-11T12:00:00-04:00",
        sender="user-agent",
        action=action,
        action_data={"cl_name": cl_name, "raw_suffix": "20260507090000"},
    )


def _make_plan_approval(*, n_id: str = "p1") -> Notification:
    return Notification(
        id=n_id,
        timestamp="2026-05-11T12:00:00-04:00",
        sender="user-agent",
        action="PlanApproval",
        action_data={"agent_cl_name": "demo"},
    )


class _FakeApp(AgentNotificationMixin):
    """Minimal stand-in for ``AceApp`` covering the bits Phase 2 touches."""

    def __init__(self) -> None:
        self._agent_completion_dismiss_inflight = False
        self._agent_completion_ack_latch = False
        self.refresh_async_calls = 0
        self.worker_calls: list[bool] = []

    async def _refresh_notification_count_async(self) -> None:  # type: ignore[override]
        self.refresh_async_calls += 1

    def run_worker(self, work, *, exclusive=False, name=""):  # noqa: ANN001
        # ``work`` is a coroutine: schedule it on the current event loop.
        self.worker_calls.append(True)
        return asyncio.get_event_loop().create_task(work)


def test_is_agent_completion_notification_matches_jump_to_agent() -> None:
    assert _is_agent_completion_notification(_make_completion())


def test_is_agent_completion_notification_matches_view_error_report() -> None:
    assert _is_agent_completion_notification(_make_completion(action="ViewErrorReport"))


def test_is_agent_completion_notification_rejects_plan_approval() -> None:
    assert not _is_agent_completion_notification(_make_plan_approval())


def test_is_agent_completion_notification_rejects_missing_cl_name() -> None:
    n = Notification(
        id="x",
        timestamp="2026-05-11T12:00:00-04:00",
        sender="user-agent",
        action="JumpToAgent",
        action_data={},
    )
    assert not _is_agent_completion_notification(n)


def test_is_agent_completion_notification_rejects_non_user_agent_sender() -> None:
    n = _make_completion()
    n.sender = "crs"
    assert not _is_agent_completion_notification(n)


@pytest.mark.asyncio
async def test_helper_dismisses_and_refreshes_when_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeApp()
    app._agent_completion_ack_latch = True

    dismiss = MagicMock(return_value=3)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications", dismiss
    )

    await app._dismiss_agent_completion_notifications_for_agents_tab()

    dismiss.assert_called_once_with()
    assert app.refresh_async_calls == 1
    assert app._agent_completion_ack_latch is False
    assert app._agent_completion_dismiss_inflight is False


@pytest.mark.asyncio
async def test_helper_clears_latch_even_when_nothing_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeApp()
    app._agent_completion_ack_latch = True

    dismiss = MagicMock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications", dismiss
    )

    await app._dismiss_agent_completion_notifications_for_agents_tab()

    dismiss.assert_called_once_with()
    # No refresh when nothing changed.
    assert app.refresh_async_calls == 0
    assert app._agent_completion_ack_latch is False


@pytest.mark.asyncio
async def test_helper_short_circuits_when_latch_clear_and_not_forced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeApp()
    dismiss = MagicMock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications", dismiss
    )

    await app._dismiss_agent_completion_notifications_for_agents_tab()

    dismiss.assert_not_called()
    assert app.refresh_async_calls == 0


@pytest.mark.asyncio
async def test_helper_runs_on_force_even_without_latch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _FakeApp()
    dismiss = MagicMock(return_value=2)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications", dismiss
    )

    await app._dismiss_agent_completion_notifications_for_agents_tab(force=True)

    dismiss.assert_called_once_with()
    assert app.refresh_async_calls == 1


@pytest.mark.asyncio
async def test_helper_skips_when_inflight(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakeApp()
    app._agent_completion_dismiss_inflight = True
    app._agent_completion_ack_latch = True
    dismiss = MagicMock(return_value=5)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications", dismiss
    )

    await app._dismiss_agent_completion_notifications_for_agents_tab(force=True)

    dismiss.assert_not_called()
    # The latch remains armed so the next request can retry.
    assert app._agent_completion_ack_latch is True
    assert app._agent_completion_dismiss_inflight is True


def test_request_helper_no_op_when_latch_clear() -> None:
    app = _FakeApp()
    app._request_agent_completion_dismiss()
    assert app.worker_calls == []


def test_request_helper_no_op_when_inflight() -> None:
    app = _FakeApp()
    app._agent_completion_dismiss_inflight = True
    app._agent_completion_ack_latch = True
    app._request_agent_completion_dismiss(force=True)
    assert app.worker_calls == []


@pytest.mark.asyncio
async def test_request_helper_spawns_worker_on_force(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dismiss = MagicMock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications", dismiss
    )

    app = _FakeApp()
    app._request_agent_completion_dismiss(force=True)
    assert app.worker_calls == [True]
    # Drain the spawned task so dismiss runs and asserts cleanly.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    dismiss.assert_called_once_with()


@pytest.mark.asyncio
async def test_request_helper_spawns_worker_when_latch_armed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dismiss = MagicMock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications", dismiss
    )

    app = _FakeApp()
    app._agent_completion_ack_latch = True
    app._request_agent_completion_dismiss()
    assert app.worker_calls == [True]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    dismiss.assert_called_once_with()


def test_record_user_activity_triggers_dismiss_on_agents_tab() -> None:
    """``_record_user_activity`` triggers a forced dismiss when on agents tab."""
    import time

    from sase.ace.tui.actions.event_handlers import EventHandlersMixin

    class _ActivityApp(EventHandlersMixin):
        def __init__(self) -> None:
            self._pinned_idle = False
            self._last_activity_time = time.monotonic()
            self._last_activity_flush = time.monotonic()
            self.current_tab = "agents"
            self._activity_log = MagicMock()
            self._indicator = MagicMock()
            self._indicator._idle = False
            self.dismiss_requests: list[bool] = []

        def query_one(self, selector, _type=None):  # noqa: ANN001
            return self._indicator

        def _request_agent_completion_dismiss(self, *, force: bool = False) -> None:
            self.dismiss_requests.append(force)

    app = _ActivityApp()
    app._record_user_activity()
    assert app.dismiss_requests == [False]


@pytest.mark.asyncio
async def test_poll_agent_completions_arms_latch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Polling sets the ack latch whenever a completion notification is unread."""
    from types import SimpleNamespace

    completion = _make_completion()

    snapshot = SimpleNamespace(
        notifications=[completion],
        expired_ids=[],
        counts=SimpleNamespace(priority=0, errors=0, rest=1, muted=0),
    )

    class _PollApp(AgentNotificationMixin):
        def __init__(self) -> None:
            self._last_unread_ids = set()
            self._agents = []
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._agent_completion_dismiss_inflight = False
            self._agent_completion_ack_latch = False
            self._indicator = MagicMock()
            self.bell_rings = 0

        def _ring_tmux_bell(self) -> None:
            self.bell_rings += 1

        def notify(self, *_args, **_kwargs) -> None:  # noqa: ANN002
            pass

        def query_one(self, selector, _type=None):  # noqa: ANN001
            return self._indicator

    app = _PollApp()
    monkeypatch.setattr(
        "sase.notifications.read_notification_snapshot", lambda *a, **k: snapshot
    )

    await app._poll_agent_completions()

    assert app._agent_completion_ack_latch is True


@pytest.mark.asyncio
async def test_poll_does_not_arm_latch_for_non_completion_notifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    plan = _make_plan_approval()
    snapshot = SimpleNamespace(
        notifications=[plan],
        expired_ids=[],
        counts=SimpleNamespace(priority=1, errors=0, rest=0, muted=0),
    )

    class _PollApp(AgentNotificationMixin):
        def __init__(self) -> None:
            self._last_unread_ids = set()
            self._agents = []
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._agent_completion_dismiss_inflight = False
            self._agent_completion_ack_latch = False
            self._indicator = MagicMock()

        def _ring_tmux_bell(self) -> None:
            pass

        def notify(self, *_args, **_kwargs) -> None:  # noqa: ANN002
            pass

        def query_one(self, selector, _type=None):  # noqa: ANN001
            return self._indicator

    app = _PollApp()
    monkeypatch.setattr(
        "sase.notifications.read_notification_snapshot", lambda *a, **k: snapshot
    )

    await app._poll_agent_completions()

    assert app._agent_completion_ack_latch is False


def test_record_user_activity_skips_dismiss_on_other_tabs() -> None:
    import time

    from sase.ace.tui.actions.event_handlers import EventHandlersMixin

    class _ActivityApp(EventHandlersMixin):
        def __init__(self) -> None:
            self._pinned_idle = False
            self._last_activity_time = time.monotonic()
            self._last_activity_flush = time.monotonic()
            self.current_tab = "changespecs"
            self._activity_log = MagicMock()
            self._indicator = MagicMock()
            self._indicator._idle = False
            self.dismiss_requests: list[bool] = []

        def query_one(self, selector, _type=None):  # noqa: ANN001
            return self._indicator

        def _request_agent_completion_dismiss(self, *, force: bool = False) -> None:
            self.dismiss_requests.append(force)

    app = _ActivityApp()
    app._record_user_activity()
    assert app.dismiss_requests == []
