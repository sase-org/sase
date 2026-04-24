"""Tests for the async startup wiring that keeps the stopwatch ticking.

These tests lock in the contract used by
``plans/202604/startup_stopwatch_live_update.md``: ``AceApp.on_mount`` is
a coroutine (so awaits between disk reads yield to the event loop and
``KeybindingFooter._on_stopwatch_tick`` fires), and the new split
helpers are pure disk reads with no Textual widget access.
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.actions.changespec import ChangeSpecMixin
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.app import AceApp


def test_on_mount_is_coroutine() -> None:
    """``AceApp.on_mount`` must be async so each disk read can yield."""
    assert inspect.iscoroutinefunction(AceApp.on_mount)


def test_try_startup_fallback_async_is_coroutine() -> None:
    """Fallback path must also be async to keep the event loop free."""
    assert inspect.iscoroutinefunction(ChangeSpecMixin._try_startup_fallback_async)


def test_read_changespecs_from_disk_returns_list() -> None:
    """Pure read helper must return whatever ``find_all_changespecs`` does."""
    mixin = ChangeSpecMixin.__new__(ChangeSpecMixin)
    sentinel = [MagicMock(), MagicMock()]
    with patch(
        "sase.ace.changespec.find_all_changespecs",
        return_value=sentinel,
    ):
        result = mixin._read_changespecs_from_disk()
    assert result is sentinel


def test_read_unread_notification_ids_returns_set() -> None:
    """Pure read helper filters to unread+non-silent and returns ids only."""
    mixin = LifecycleMixin.__new__(LifecycleMixin)
    n_read = MagicMock(id="a", read=True, silent=False)
    n_silent = MagicMock(id="b", read=False, silent=True)
    n_unread = MagicMock(id="c", read=False, silent=False)
    with patch(
        "sase.notifications.load_notifications",
        return_value=[n_read, n_silent, n_unread],
    ):
        result = mixin._read_unread_notification_ids()
    assert result == {"c"}


def test_read_last_selection_name_delegates_to_loader() -> None:
    """Pure read helper forwards whatever ``load_last_selection`` returns."""
    mixin = LifecycleMixin.__new__(LifecycleMixin)
    with patch(
        "sase.ace.last_selection.load_last_selection",
        return_value="foo",
    ):
        assert mixin._read_last_selection_name() == "foo"
    with patch(
        "sase.ace.last_selection.load_last_selection",
        return_value=None,
    ):
        assert mixin._read_last_selection_name() is None


def test_start_post_mount_background_loads_schedules_both_once() -> None:
    """Startup launcher should schedule agent and axe startup paths once."""
    app = AceApp()
    scheduled: list[object] = []

    with patch.object(
        app,
        "run_worker",
        side_effect=lambda fn, **kwargs: scheduled.append(fn),
    ):
        app._start_post_mount_background_loads()
        app._start_post_mount_background_loads()

    assert scheduled.count(app._run_agents_async_refresh) == 1
    assert scheduled.count(app._run_axe_startup_init) == 1
    assert app._post_mount_background_loads_started is True


@pytest.mark.asyncio
async def test_start_post_mount_background_loads_does_not_gate_axe_on_agents() -> None:
    """Axe startup should complete even while agents startup is still running."""

    class _Harness:
        def __init__(self) -> None:
            self._post_mount_background_loads_started = False
            self.agent_started = asyncio.Event()
            self.agent_release = asyncio.Event()
            self.agent_done = asyncio.Event()
            self.axe_done = asyncio.Event()
            self.tasks: list[asyncio.Task[None]] = []

        async def _run_agents_async_refresh(self) -> None:
            self.agent_started.set()
            await self.agent_release.wait()
            self.agent_done.set()

        async def _run_axe_startup_init(self) -> None:
            self.axe_done.set()

        def run_worker(self, fn, **kwargs) -> None:  # type: ignore[no-untyped-def]
            del kwargs
            self.tasks.append(asyncio.create_task(fn()))

    harness = _Harness()
    AceApp._start_post_mount_background_loads(harness)  # type: ignore[arg-type]

    await asyncio.wait_for(harness.agent_started.wait(), timeout=0.2)
    await asyncio.wait_for(harness.axe_done.wait(), timeout=0.2)
    assert not harness.agent_done.is_set()

    harness.agent_release.set()
    await asyncio.wait_for(asyncio.gather(*harness.tasks), timeout=0.2)
