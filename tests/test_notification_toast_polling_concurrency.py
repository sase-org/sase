"""Tests for off-thread bells and shared snapshot reads during toast polling."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import patch

from tests._notification_toasts_helpers import (
    _FakeApp,
    _make,
    _patch_snapshot,
    _snapshot,
)


class TestRingTmuxBellNonBlocking:
    """Phase 1 (sase-3q.1): the tmux bell must not block the event-loop thread."""

    def test_bell_runs_off_event_loop_thread(self) -> None:
        app = _FakeApp()
        new_notif = _make(action="UserQuestion", notes=["q?"])

        loop_thread: list[threading.Thread] = []
        bell_thread: list[threading.Thread] = []

        def _capture_bell_thread() -> None:
            bell_thread.append(threading.current_thread())

        app._ring_tmux_bell = _capture_bell_thread  # type: ignore[method-assign]

        async def _run() -> None:
            loop_thread.append(threading.current_thread())
            await app._poll_agent_completions()

        with _patch_snapshot([new_notif]):
            asyncio.run(_run())

        assert bell_thread, "bell was never invoked"
        assert bell_thread[0] is not loop_thread[0]

    def test_blocking_bell_does_not_delay_toast_or_indicator(self) -> None:
        """A bell that blocks on the worker thread must not stall the event loop."""
        app = _FakeApp()
        new_notif = _make(action="UserQuestion", notes=["q?"])

        bell_started = threading.Event()
        bell_release = threading.Event()
        notify_count_when_bell_started: list[int] = []
        indicator_when_bell_started: list[int | None] = []

        def _blocking_bell() -> None:
            notify_count_when_bell_started.append(app.notify.call_count)
            indicator_when_bell_started.append(app._indicator_count)
            bell_started.set()
            assert bell_release.wait(timeout=5.0)

        app._ring_tmux_bell = _blocking_bell  # type: ignore[method-assign]

        async def _run() -> None:
            poll_task = asyncio.create_task(app._poll_agent_completions())
            assert await asyncio.to_thread(bell_started.wait, 2.0)
            bell_release.set()
            await poll_task

        with _patch_snapshot([new_notif]):
            asyncio.run(_run())

        assert notify_count_when_bell_started == [1]
        assert indicator_when_bell_started == [1]


class TestNotificationSnapshotSingleFlight:
    """Section 3: overlapping snapshot readers share one direct-store parse."""

    async def _wait_for_pending(self, app: _FakeApp) -> None:
        for _ in range(1000):
            if getattr(app, "_notification_snapshot_read_pending", False):
                return
            await asyncio.sleep(0)
        raise AssertionError("count refresh never registered as pending")

    def test_overlapping_poll_and_count_refresh_share_one_parse(self) -> None:
        """A completion poll and a scheduled count refresh must not double-parse."""
        app = _FakeApp()
        notif = _make(action="JumpToAgent", notes=["done"])

        read_started = threading.Event()
        release_read = threading.Event()
        call_count = 0
        lock = threading.Lock()

        def _slow_read(*_args: object, **_kwargs: object) -> object:
            nonlocal call_count
            with lock:
                call_count += 1
                this_call = call_count
            if this_call == 1:
                read_started.set()
                assert release_read.wait(timeout=5.0)
            return _snapshot([notif])

        async def _run() -> bool:
            poll_task = asyncio.create_task(app._poll_agent_completions())
            await asyncio.to_thread(read_started.wait, 2.0)
            count_task = asyncio.create_task(app._refresh_notification_count_async())
            await self._wait_for_pending(app)
            release_read.set()
            saw_new = await poll_task
            await count_task
            return saw_new

        with patch(
            "sase.notifications.read_notification_snapshot", side_effect=_slow_read
        ):
            saw_new = asyncio.run(_run())

        assert saw_new is True
        # One shared parse for the poll plus one bounded follow-up to
        # satisfy the count refresh that arrived mid-read -- never one
        # parse per caller.
        assert call_count == 2
        assert app._indicator_count == 1
