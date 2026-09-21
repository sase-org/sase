"""Tests for startup wiring that keeps first paint and input responsive.

These tests lock in the contract used by
``sdd/plans/202604/startup_stopwatch_live_update.md``: ``AceApp.on_mount``
finishes synchronously, post-mount workers perform disk reads after first
paint, and the split helpers are pure disk reads with no Textual widget access.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.actions.axe_display._data import AxeCollectedData
from sase.ace.tui.actions.patch import PatchMixin
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.modals.notification_modal_tags import NotificationTagTab
from sase.ace.tui.app import AceApp
from sase.ace.testing import AcePage

from tests._notification_toasts_helpers import _FakeApp, _make, _patch_snapshot


def test_on_mount_is_synchronous() -> None:
    """``AceApp.on_mount`` must return before any slow disk body runs."""
    assert not inspect.iscoroutinefunction(AceApp.on_mount)
    assert "to_thread" not in inspect.getsource(AceApp.on_mount)


def test_on_mount_seeds_current_tab_in_trace_context() -> None:
    """``on_mount`` seeds the trace context with ``current_tab`` up front.

    Without this seed, startup-phase spans (notifications read,
    patches read, the first agents/axe loads) all emit
    ``current_tab=None`` because ``watch_current_tab`` only fires on
    later transitions.
    """
    src = inspect.getsource(AceApp.on_mount)
    assert "set_trace_context(current_tab=self.current_tab)" in src
    # Must be inside the ``self._mounting = True`` block, before the
    # first widget access, so the seed precedes any span emission.
    mounting_idx = src.index("self._mounting = True")
    seed_idx = src.index("set_trace_context(current_tab=self.current_tab)")
    first_query_idx = src.index("self.query_one")
    assert mounting_idx < seed_idx < first_query_idx


def test_first_paint_marker_precedes_non_frame_startup_services() -> None:
    """Non-visible services must wait until after the first frame is marked."""
    mount_src = inspect.getsource(AceApp.on_mount)
    assert "_schedule_link_index_refresh" not in mount_src
    assert "_start_proc_reconciler" not in mount_src
    assert "start_event_loop_stall_watchdog" not in mount_src
    assert "start_tui_heap_sampler" not in mount_src
    assert '"auto-refresh"' not in mount_src

    launcher_src = inspect.getsource(AceApp._start_post_mount_background_loads)
    first_paint_idx = launcher_src.index("self._mark_startup_first_paint()")
    services_idx = launcher_src.index("self._start_post_first_paint_services()")
    fallback_idx = launcher_src.index("self._arm_startup_deferred_fallback()")
    immediate_idx = launcher_src.index("self._start_immediate_startup_loads()")
    assert first_paint_idx < services_idx < fallback_idx < immediate_idx


def test_read_patches_from_disk_returns_list() -> None:
    """Pure read helper must return whatever the cached loader does."""
    mixin = PatchMixin.__new__(PatchMixin)
    sentinel = [MagicMock(), MagicMock()]
    with patch(
        "sase.ace.patch.find_all_patches_cached",
        return_value=sentinel,
    ):
        result = mixin._read_patches_from_disk()
    assert result is sentinel


def test_read_unread_notification_ids_returns_set() -> None:
    """Pure read helper filters to unread+non-silent+non-muted and returns ids only."""
    mixin = LifecycleMixin.__new__(LifecycleMixin)
    n_read = MagicMock(id="a", read=True, silent=False, muted=False)
    n_silent = MagicMock(id="b", read=False, silent=True, muted=False)
    n_muted = MagicMock(id="d", read=False, silent=False, muted=True)
    n_unread = MagicMock(id="c", read=False, silent=False, muted=False)
    with patch(
        "sase.notifications.read_notification_snapshot",
        return_value=SimpleNamespace(
            notifications=[n_read, n_silent, n_muted, n_unread]
        ),
    ):
        result = mixin._read_unread_notification_ids()
    assert result == {"c"}


def test_read_notifications_for_startup_uses_snapshot_tabs() -> None:
    """Startup indicator chips come from the Rust-backed snapshot tabs."""
    mixin = LifecycleMixin.__new__(LifecycleMixin)
    timestamp = "2026-08-01T09:00:00-04:00"
    n_priority = MagicMock(
        id="a",
        read=False,
        silent=False,
        muted=False,
        timestamp=timestamp,
        resurfaced_at=None,
    )
    n_muted = MagicMock(
        id="b",
        read=False,
        silent=False,
        muted=True,
        timestamp="2026-08-01T09:01:00-04:00",
        resurfaced_at=None,
    )
    snapshot = SimpleNamespace(
        notifications=[n_priority, n_muted],
        counts=SimpleNamespace(priority=7, errors=4, rest=3, muted=2),
        tabs=[
            SimpleNamespace(
                key="hitl",
                kind="hitl",
                count=7,
                oldest_activity_at=timestamp,
                next_wake_at=None,
                color=None,
            ),
            SimpleNamespace(
                key="__muted__",
                kind="muted",
                count=2,
                oldest_activity_at=None,
                next_wake_at=None,
                color=None,
            ),
        ],
    )
    with patch("sase.notifications.read_notification_snapshot", return_value=snapshot):
        assert mixin._read_notifications_for_startup() == (
            {"a"},
            {(timestamp, "a")},
            [
                NotificationTagTab(
                    tag="hitl",
                    label="Gates",
                    count=7,
                    kind="hitl",
                    oldest_activity_at=timestamp,
                ),
                NotificationTagTab(
                    tag="__muted__",
                    label="Muted",
                    count=2,
                    kind="muted",
                ),
            ],
        )


def test_startup_seeded_activity_generation_does_not_toast_after_startup() -> None:
    app = _FakeApp()
    existing = _make(
        id="existing-startup",
        action="JumpToAgent",
        notes=["already active"],
        timestamp="2026-08-01T09:00:00-04:00",
    )

    with _patch_snapshot([existing]) as startup_read:
        app._initialize_agent_tracking(app._read_notifications_for_startup())

    startup_read.assert_called_once()
    assert app._last_unread_ids == {existing.id}
    assert app._delivered_notification_activity_cursors == {
        ("2026-08-01T09:00:00-04:00", existing.id)
    }

    with _patch_snapshot([existing]):
        saw_new = asyncio.run(app._poll_agent_completions())

    assert saw_new is False
    assert app.notify.call_count == 0
    assert app._bell_rung == 0


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


def test_start_post_mount_background_loads_starts_visible_agents_first() -> None:
    """Default startup keeps hidden/deferred work behind the Agents first load."""
    app = AceApp()
    app._mark_startup_on_mount()
    scheduled: list[object] = []
    timers: list[tuple[float, object, str | None, MagicMock]] = []

    def capture_timer(
        seconds: float,
        callback: Callable[[], None],
        **kwargs: object,
    ) -> MagicMock:
        timer = MagicMock()
        timers.append((seconds, callback, kwargs.get("name"), timer))
        return timer

    with (
        patch.object(
            app,
            "run_worker",
            side_effect=lambda fn, **kwargs: scheduled.append(fn),
        ),
        patch.object(app, "_start_post_first_paint_services") as post_paint_services,
        patch.object(app, "set_timer", side_effect=capture_timer),
        patch.object(app, "set_interval", return_value=MagicMock()),
        patch.object(app, "_start_artifact_watcher"),
        patch.object(app, "_start_prompt_source_watcher"),
        patch.object(app, "_maybe_show_post_update_toast", return_value=False),
        patch.object(app, "_schedule_link_index_refresh") as link_refresh,
    ):
        app._start_post_mount_background_loads()
        app._start_post_mount_background_loads()

        assert scheduled.count(app._run_mount_notification_state_loads) == 1
        assert scheduled.count(app._run_agent_index_startup_prepare_and_refresh) == 1
        assert scheduled.count(app._run_agents_fold_state_load) == 1
        assert app._run_axe_startup_init not in scheduled
        assert app._run_deferred_mount_state_loads not in scheduled
        assert app._run_dismissed_proc_shells_startup_prune not in scheduled
        assert app._run_startup_update_toast_check not in scheduled
        post_paint_services.assert_called_once_with()
        link_refresh.assert_not_called()
        assert timers == [
            (
                3.0,
                app._release_startup_deferred_loads_from_fallback,
                "startup-deferred-fallback",
                timers[0][3],
            ),
        ]
        assert app._post_mount_background_loads_started is True

        app._agents_first_load_done = True
        app._mark_startup_agents_ready()
        app._maybe_end_startup_stopwatch()
        link_refresh.assert_called_once_with(source="startup_visible_ready")

    assert scheduled.count(app._run_agent_index_startup_prepare_and_refresh) == 1
    assert scheduled.count(app._run_axe_startup_init) == 1
    assert scheduled.count(app._run_deferred_mount_state_loads) == 1
    assert scheduled.count(app._run_dismissed_proc_shells_startup_prune) == 1
    assert scheduled.count(app._run_startup_update_toast_check) == 1
    timers[0][3].stop.assert_called_once()
    assert app._startup_deferred_loads_released is True


def test_startup_fallback_releases_deferred_without_visible_ready() -> None:
    """Fallback starts hidden work but does not falsely stamp visible-ready."""
    app = AceApp()
    app._mark_startup_on_mount()
    scheduled: list[object] = []
    fallback: Callable[[], None] | None = None

    def capture_timer(
        _seconds: float,
        callback: Callable[[], None],
        **_kwargs: object,
    ) -> MagicMock:
        nonlocal fallback
        fallback = callback
        return MagicMock()

    with (
        patch.object(
            app,
            "run_worker",
            side_effect=lambda fn, **kwargs: scheduled.append(fn),
        ),
        patch.object(app, "_start_post_first_paint_services"),
        patch.object(app, "set_timer", side_effect=capture_timer),
        patch.object(app, "set_interval", return_value=MagicMock()),
        patch.object(app, "_start_artifact_watcher"),
        patch.object(app, "_start_prompt_source_watcher"),
        patch.object(app, "_maybe_show_post_update_toast", return_value=False),
    ):
        app._start_post_mount_background_loads()
        assert fallback is not None
        fallback()

    assert app._startup_visible_ready_mono is None
    assert app._startup_deferred_loads_released is True
    assert app._startup_deferred_release_reason == "fallback"
    assert scheduled.count(app._run_agent_index_startup_prepare_and_refresh) == 1
    assert scheduled.count(app._run_axe_startup_init) == 1
    assert scheduled.count(app._run_deferred_mount_state_loads) == 1
    assert scheduled.count(app._run_dismissed_proc_shells_startup_prune) == 1


def test_initial_axe_startup_starts_axe_before_agents() -> None:
    """Initial AXE mode makes AXE the visible startup prerequisite."""
    app = AceApp(initial_tab="axe")
    app._mark_startup_on_mount()
    scheduled: list[object] = []

    with (
        patch.object(
            app,
            "run_worker",
            side_effect=lambda fn, **kwargs: scheduled.append(fn),
        ),
        patch.object(app, "_start_post_first_paint_services"),
        patch.object(app, "set_timer", return_value=MagicMock()),
        patch.object(app, "set_interval", return_value=MagicMock()),
        patch.object(app, "_start_artifact_watcher"),
        patch.object(app, "_start_prompt_source_watcher"),
    ):
        app._start_post_mount_background_loads()

    assert scheduled.count(app._run_axe_startup_init) == 1
    assert app._run_agent_index_startup_prepare_and_refresh not in scheduled
    assert app._run_deferred_mount_state_loads not in scheduled


def test_initial_artifacts_startup_releases_after_first_paint() -> None:
    """Initial Artifacts mode has no async visible-surface prerequisite."""
    app = AceApp(initial_tab="patches")
    app._mark_startup_on_mount()
    scheduled: list[object] = []

    with (
        patch.object(
            app,
            "run_worker",
            side_effect=lambda fn, **kwargs: scheduled.append(fn),
        ),
        patch.object(app, "_start_post_first_paint_services"),
        patch.object(app, "set_timer", return_value=MagicMock()),
        patch.object(app, "set_interval", return_value=MagicMock()),
        patch.object(app, "_start_artifact_watcher"),
        patch.object(app, "_start_prompt_source_watcher"),
        patch.object(app, "_maybe_show_post_update_toast", return_value=False),
    ):
        app._start_post_mount_background_loads()

    assert app._startup_initial_tab == "artifacts"
    assert app._startup_visible_ready_mono is not None
    assert app._startup_deferred_loads_released is True
    assert scheduled.count(app._run_deferred_mount_state_loads) == 1
    assert scheduled.count(app._run_agent_index_startup_prepare_and_refresh) == 1
    assert scheduled.count(app._run_axe_startup_init) == 1


def test_startup_tab_switch_does_not_duplicate_surface_load() -> None:
    """A startup tab switch can request the hidden surface once."""
    app = AceApp()
    app._mark_startup_on_mount()
    scheduled: list[object] = []

    with (
        patch.object(
            app,
            "run_worker",
            side_effect=lambda fn, **kwargs: scheduled.append(fn),
        ),
        patch.object(app, "_start_post_first_paint_services"),
        patch.object(app, "set_timer", return_value=MagicMock()),
        patch.object(app, "set_interval", return_value=MagicMock()),
        patch.object(app, "_start_artifact_watcher"),
        patch.object(app, "_start_prompt_source_watcher"),
    ):
        app._start_post_mount_background_loads()
        assert app._maybe_start_startup_surface_for_tab("services") is True
        app._agents_first_load_done = True
        app._mark_startup_agents_ready()
        app._maybe_end_startup_stopwatch()

    assert scheduled.count(app._run_agent_index_startup_prepare_and_refresh) == 1
    assert scheduled.count(app._run_axe_startup_init) == 1


@pytest.mark.asyncio
async def test_slow_mount_state_read_does_not_block_app_key_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first slow post-mount read must not occupy the App message pump."""
    started = Event()
    release = Event()

    def slow_notifications(
        _self: AceApp,
    ) -> tuple[set[str], set[tuple[str, str]], list[NotificationTagTab]]:
        started.set()
        release.wait()
        return set(), set(), []

    monkeypatch.setattr(AceApp, "_read_notifications_for_startup", slow_notifications)

    async with AcePage(
        wait_for_startup_state=False,
        startup_policy="real",
    ) as page:
        try:
            assert await asyncio.wait_for(
                asyncio.to_thread(started.wait, 10.0), timeout=11.0
            )
            assert page.app.current_tab == "artifacts"
            await page.press("tab")
            await page.wait_for(
                lambda _state: page.app.current_tab != "artifacts",
            )
            assert page.app.current_tab == "services"
        finally:
            release.set()
            await page.wait_for(
                lambda _state: page.app._mount_state_loads_done,
                timeout=15.0,
            )


def test_startup_configures_periodic_update_interval_from_loaded_config() -> None:
    with patch(
        "sase.config.load_merged_config",
        return_value={"ace": {"updates": {"check_interval_minutes": 1.5}}},
    ):
        app = AceApp()
    intervals: list[tuple[float, object, str | None]] = []

    with patch.object(
        app,
        "set_interval",
        side_effect=lambda seconds, callback, **kwargs: (
            intervals.append((seconds, callback, kwargs.get("name"))) or MagicMock()
        ),
    ):
        app._start_periodic_update_checks()

    assert app._automatic_update_check_interval_seconds == 90.0
    assert intervals == [
        (90.0, app._on_periodic_update_check, "automatic-update-check")
    ]


@pytest.mark.asyncio
async def test_start_post_mount_background_loads_gates_axe_on_agents_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Axe startup waits for the visible Agents surface unless fallback releases it."""
    app = AceApp()
    app._mark_startup_on_mount()
    agent_started = asyncio.Event()
    agent_release = asyncio.Event()
    agent_done = asyncio.Event()
    axe_done = asyncio.Event()
    fold_started = asyncio.Event()
    fold_release = asyncio.Event()
    fold_done = asyncio.Event()
    deferred_done = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []

    async def agents() -> None:
        agent_started.set()
        await agent_release.wait()
        app._agents_first_load_done = True
        app._mark_startup_agents_ready()
        app._maybe_end_startup_stopwatch()
        agent_done.set()

    async def axe() -> None:
        axe_done.set()

    async def fold() -> None:
        fold_started.set()
        await fold_release.wait()
        fold_done.set()

    async def notifications() -> None:
        app._mount_notification_state_load_done = True
        app._maybe_mark_mount_state_loads_done()

    async def deferred_mount_state() -> None:
        app._mount_deferred_state_load_done = True
        app._maybe_mark_mount_state_loads_done()
        deferred_done.set()

    def run_worker(fn, **kwargs) -> None:  # type: ignore[no-untyped-def]
        del kwargs
        tasks.append(asyncio.create_task(fn()))

    monkeypatch.setattr(app, "run_worker", run_worker)
    monkeypatch.setattr(
        app,
        "_run_agent_index_startup_prepare_and_refresh",
        agents,
    )
    monkeypatch.setattr(app, "_run_axe_startup_init", axe)
    monkeypatch.setattr(app, "_run_agents_fold_state_load", fold)
    monkeypatch.setattr(app, "_run_mount_notification_state_loads", notifications)
    monkeypatch.setattr(app, "_run_deferred_mount_state_loads", deferred_mount_state)
    monkeypatch.setattr(app, "_start_post_first_paint_services", lambda: None)
    monkeypatch.setattr(
        app,
        "_schedule_deferred_startup_maintenance",
        lambda *, reason: None,
    )
    monkeypatch.setattr(app, "_start_artifact_watcher", lambda: None)
    monkeypatch.setattr(app, "_start_prompt_source_watcher", lambda: None)
    monkeypatch.setattr(app, "set_timer", lambda *_args, **_kwargs: MagicMock())

    app._start_post_mount_background_loads()

    await asyncio.wait_for(agent_started.wait(), timeout=0.2)
    await asyncio.wait_for(fold_started.wait(), timeout=0.2)
    assert not axe_done.is_set()
    assert not deferred_done.is_set()
    assert not agent_done.is_set()
    assert not fold_done.is_set()

    agent_release.set()
    fold_release.set()
    await asyncio.wait_for(agent_done.wait(), timeout=1.0)
    await asyncio.wait_for(axe_done.wait(), timeout=1.0)
    await asyncio.wait_for(deferred_done.wait(), timeout=1.0)
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=1.0)


def test_maybe_end_startup_stopwatch_gates_on_visible_tab_only() -> None:
    """Coordinator ends the stopwatch once the initially visible tab is ready.

    The hidden tab's own load state must not matter — that is the point of
    the visible-surface gate: a future hidden-tab feature cannot regress
    every startup mode just by taking longer to finish loading.
    """
    app = AceApp()
    footer = MagicMock()

    with patch.object(app, "query_one", return_value=footer):
        app._startup_initial_tab = "agents"
        app._agents_first_load_done = False
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()
        footer.end_startup_stopwatch.assert_not_called()

        app._agents_first_load_done = True
        app._maybe_end_startup_stopwatch()

    footer.end_startup_stopwatch.assert_called_once()


def test_maybe_end_startup_stopwatch_clears_startup_window_flag() -> None:
    """Visible-ready ends the tagged startup window so later spans omit it."""
    from sase.ace.tui.util import trace

    app = AceApp()
    footer = MagicMock()
    trace.set_startup_window(True)
    with patch.object(app, "query_one", return_value=footer):
        app._startup_initial_tab = "agents"
        app._agents_first_load_done = True
        app._maybe_end_startup_stopwatch()
    assert trace._startup_window is False
    footer.end_startup_stopwatch.assert_called_once()


def test_maybe_end_startup_stopwatch_gates_on_axe_when_axe_is_visible() -> None:
    """When axe is the initially visible tab, only its readiness gates."""
    app = AceApp()
    footer = MagicMock()

    with patch.object(app, "query_one", return_value=footer):
        app._startup_initial_tab = "services"
        app._agents_first_load_done = False
        app._axe_first_load_done = False
        app._maybe_end_startup_stopwatch()
        footer.end_startup_stopwatch.assert_not_called()

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
        app._startup_initial_tab = "agents"
        app._agents_first_load_done = True
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()
        app._maybe_end_startup_stopwatch()

    assert footer.end_calls == 1


def test_axe_first_load_path_no_longer_ends_stopwatch_directly() -> None:
    """AXE first-load applies must route through the coordinator (not direct end)."""
    app = AceApp()
    app._startup_initial_tab = "agents"
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
        axe_output="",
        lumberjack_names=[],
        bgcmd_slots=[],
        lumberjack_statuses={},
        lumberjack_metrics={},
        lumberjack_log_tails={},
        bgcmd_details={},
        lumberjack_chop_names={},
        chop_snapshots={},
        lumberjack_snapshots={},
    )

    with (
        patch.object(app, "query_one", side_effect=_query_one),
        patch.object(app, "_update_bgcmd_count", return_value=None),
        patch.object(app, "_build_axe_items", return_value=None),
        patch.object(app, "_update_axe_keybinding", return_value=None),
    ):
        app._apply_axe_status_data(data)

    footer.end_startup_stopwatch.assert_not_called()


def test_stopwatch_ends_as_soon_as_visible_surface_finishes_first() -> None:
    """The hidden surface finishing later must not be required to end it."""

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
    app._startup_initial_tab = "agents"
    footer = _Footer()

    with patch.object(app, "query_one", return_value=footer):
        # The hidden (axe) surface finishing first must not end it early.
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()
        assert footer.end_calls == 0

        # The visible (agents) surface finishing ends it immediately.
        app._agents_first_load_done = True
        app._maybe_end_startup_stopwatch()
        assert footer.end_calls == 1
