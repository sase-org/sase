"""Deterministic coverage for ACE's nearest-snooze-deadline coordinator."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._notification_deadlines import (
    AgentNotificationDeadlineMixin,
)
from sase.ace.tui.actions.agents._notification_polling import (
    AgentNotificationPollingMixin,
)
from sase.ace.tui.actions.agents._notification_provider_direct import (
    notification_snapshot_from_direct,
)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


class _FakeTimer:
    def __init__(self, delay: float, callback: Any, name: str | None) -> None:
        self.delay = delay
        self.callback = callback
        self.name = name
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _DeadlineApp(AgentNotificationDeadlineMixin):
    def __init__(self) -> None:
        self._notification_deadline_timer: _FakeTimer | None = None
        self._notification_deadline_epoch: float | None = None
        self._notification_poll_pending = False
        self.timers: list[_FakeTimer] = []
        self.scheduled_sources: list[str] = []
        self.refresh_interval = 0

    def set_timer(
        self,
        delay: float,
        callback: Any,
        *,
        name: str | None = None,
    ) -> _FakeTimer:
        timer = _FakeTimer(delay, callback, name)
        self.timers.append(timer)
        return timer

    def _schedule_notification_poll(self, *, source: str = "notification") -> None:
        self.scheduled_sources.append(source)


def test_snapshot_replaces_and_cancels_the_single_nearest_timer() -> None:
    app = _DeadlineApp()
    with patch(
        "sase.ace.tui.actions.agents._notification_deadlines._notification_wall_time",
        return_value=100.0,
    ):
        app._sync_notification_deadline_from_snapshot(
            SimpleNamespace(next_snooze_deadline=_iso(110.0))
        )
        first = app.timers[-1]
        assert first.delay == 1.0

        app._sync_notification_deadline_from_snapshot(
            SimpleNamespace(next_snooze_deadline=_iso(103.0))
        )
        second = app.timers[-1]
        assert first.stopped is True
        assert second.delay == 1.0

        app._sync_notification_deadline_from_snapshot(
            SimpleNamespace(next_snooze_deadline=None)
        )

    assert second.stopped is True
    assert app._notification_deadline_timer is None
    assert app._notification_deadline_epoch is None


def test_due_deadline_launches_poll_with_general_refresh_disabled() -> None:
    app = _DeadlineApp()
    clock = [100.0]
    with patch(
        "sase.ace.tui.actions.agents._notification_deadlines._notification_wall_time",
        side_effect=lambda: clock[0],
    ):
        app._sync_notification_deadline_from_snapshot(
            SimpleNamespace(next_snooze_deadline=_iso(101.0))
        )
        timer = app.timers[-1]
        clock[0] = 101.0
        timer.callback()

    assert app.refresh_interval == 0
    assert app.scheduled_sources == ["deadline"]


def test_wall_clock_jump_rechecks_without_polling_disk_early() -> None:
    app = _DeadlineApp()
    clock = [100.0]
    with patch(
        "sase.ace.tui.actions.agents._notification_deadlines._notification_wall_time",
        side_effect=lambda: clock[0],
    ):
        app._sync_notification_deadline_from_snapshot(
            SimpleNamespace(next_snooze_deadline=_iso(105.0))
        )
        first = app.timers[-1]

        # A backward clock correction keeps the cached deadline and performs
        # only another in-memory recheck.
        clock[0] = 90.0
        first.callback()
        assert app.scheduled_sources == []
        assert app.timers[-1].delay == 1.0

        # Suspend/resume or a forward jump catches up on the next callback.
        clock[0] = 110.0
        app.timers[-1].callback()

    assert app.scheduled_sources == ["deadline"]


def test_coordinator_cleanup_stops_timer_and_drops_deadline() -> None:
    app = _DeadlineApp()
    with patch(
        "sase.ace.tui.actions.agents._notification_deadlines._notification_wall_time",
        return_value=100.0,
    ):
        app._sync_notification_deadline_from_snapshot(
            SimpleNamespace(next_snooze_deadline=_iso(105.0))
        )
    timer = app.timers[-1]

    app._cancel_notification_deadline_coordinator()

    assert timer.stopped is True
    assert app._notification_deadline_timer is None
    assert app._notification_deadline_epoch is None


@pytest.mark.asyncio
async def test_failed_watcher_read_retries_without_cached_deadline() -> None:
    app = _DeadlineApp()

    async def fail_poll() -> bool:
        raise OSError("store busy")

    app._poll_agent_completions = fail_poll  # type: ignore[attr-defined]
    await app._run_scheduled_notification_poll(source="watcher")

    retry = app.timers[-1]
    assert retry.delay == 1.0
    assert retry.name == "notification-poll-retry"
    retry.callback()
    assert app.scheduled_sources == ["retry"]


class _OverlappingPollApp(
    AgentNotificationPollingMixin, AgentNotificationDeadlineMixin
):
    def __init__(self) -> None:
        self._notification_poll_running = False
        self._notification_poll_scheduled = False
        self._notification_poll_pending = False
        self._pump_free_async_tasks: set[asyncio.Task[object]] = set()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.read_count = 0

    async def _poll_agent_completions_once(self) -> bool:
        self.read_count += 1
        if self.read_count == 1:
            self.started.set()
            await self.release.wait()
        return self.read_count == 2


@pytest.mark.asyncio
async def test_timer_poll_overlap_coalesces_to_one_trailing_read() -> None:
    app = _OverlappingPollApp()
    first = asyncio.create_task(app._poll_agent_completions())
    await app.started.wait()

    app._schedule_notification_poll(source="deadline")
    assert app._notification_poll_pending is True
    assert app._notification_poll_scheduled is False

    app.release.set()
    assert await first is True
    assert app.read_count == 2


def test_provider_preserves_core_next_deadline_metadata() -> None:
    deadline = _iso(123.0)
    snapshot = notification_snapshot_from_direct(
        SimpleNamespace(
            notifications=[],
            expired_ids=[],
            next_snooze_deadline=deadline,
            counts=SimpleNamespace(priority=0, errors=0, rest=0, muted=0),
        )
    )
    assert snapshot.next_snooze_deadline == deadline
