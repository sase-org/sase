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

from sase.ace.tui.actions.axe_display._data import AxeCollectedData
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


def test_maybe_end_startup_stopwatch_requires_both_first_load_flags() -> None:
    """Coordinator should end stopwatch only after both startup loads finish."""
    app = AceApp()
    footer = MagicMock()

    with patch.object(app, "query_one", return_value=footer):
        app._agents_first_load_done = True
        app._axe_first_load_done = False
        app._maybe_end_startup_stopwatch()

        app._agents_first_load_done = False
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()

        app._agents_first_load_done = True
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()

    footer.end_startup_stopwatch.assert_called_once()


def test_maybe_end_startup_stopwatch_is_safe_when_called_repeatedly() -> None:
    """Repeated coordinator calls rely on footer idempotency and stay safe."""

    class _Footer:
        def __init__(self) -> None:
            self.active = True
            self.end_calls = 0

        def end_startup_stopwatch(self) -> None:
            if not self.active:
                return
            self.active = False
            self.end_calls += 1

    app = AceApp()
    footer = _Footer()

    with patch.object(app, "query_one", return_value=footer):
        app._agents_first_load_done = True
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()
        app._maybe_end_startup_stopwatch()

    assert footer.end_calls == 1


def test_axe_first_load_path_no_longer_ends_stopwatch_directly() -> None:
    """AXE first-load applies must route through the coordinator (not direct end)."""
    app = AceApp()
    app._agents_first_load_done = False
    app._axe_first_load_done = False
    footer = MagicMock()

    def _query_one(selector: str, *_args: object, **_kwargs: object) -> object:
        if selector == "#axe-dashboard":
            return MagicMock()
        if selector == "#axe-info-panel":
            panel = MagicMock()
            panel.set_loading = MagicMock()
            return panel
        if selector == "#keybinding-footer":
            return footer
        return MagicMock()

    data = AxeCollectedData(
        axe_running=False,
        axe_status=None,
        axe_metrics=None,
        axe_output="",
        lumberjack_names=[],
        bgcmd_slots=[],
        lumberjack_statuses={},
        lumberjack_metrics={},
        lumberjack_log_tails={},
        bgcmd_details={},
    )

    with (
        patch.object(app, "query_one", side_effect=_query_one),
        patch.object(app, "_update_bgcmd_count", return_value=None),
        patch.object(app, "_build_axe_items", return_value=None),
        patch.object(app, "_update_axe_tab_count", return_value=None),
        patch.object(app, "_update_axe_keybinding", return_value=None),
    ):
        app._apply_axe_status_data(data)

    footer.end_startup_stopwatch.assert_not_called()


def test_stopwatch_ends_when_second_startup_surface_finishes() -> None:
    """Simulate each first-load completion path; second completion ends stopwatch."""

    class _Footer:
        def __init__(self) -> None:
            self.active = True
            self.end_calls = 0

        def end_startup_stopwatch(self) -> None:
            if not self.active:
                return
            self.active = False
            self.end_calls += 1

    app = AceApp()
    footer = _Footer()

    with patch.object(app, "query_one", return_value=footer):
        # Simulate agents first load finishing first.
        app._agents_first_load_done = True
        app._maybe_end_startup_stopwatch()
        assert footer.end_calls == 0

        # Simulate axe first load finishing second.
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()
        assert footer.end_calls == 1
