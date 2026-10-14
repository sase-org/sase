"""Post-mount startup scheduling and responsiveness tests."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from threading import Event
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.app import AceApp
from sase.ace.tui.modals.notification_modal_tags import NotificationTagTab


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
        assert app._run_dismissed_named_procs_startup_prune not in scheduled
        assert app._run_startup_update_toast_check not in scheduled
        post_paint_services.assert_called_once_with()
        link_refresh.assert_not_called()
        assert timers == [
            (
                45.0,
                app._release_startup_deferred_loads_from_fallback,
                "startup-deferred-fallback",
                timers[0][3],
            ),
        ]
        assert app._post_mount_background_loads_started is True

        app._agents_first_load_done = True
        app._mark_startup_agents_ready()
        app._maybe_end_startup_stopwatch()
        # CPU-heavy jobs (link index, update check, catalog) wait for the
        # pump-free chain; this test has no running loop so they stay idle.
        link_refresh.assert_not_called()

    assert scheduled.count(app._run_agent_index_startup_prepare_and_refresh) == 1
    assert scheduled.count(app._run_axe_startup_init) == 1
    assert scheduled.count(app._run_deferred_mount_state_loads) == 1
    assert scheduled.count(app._run_dismissed_named_procs_startup_prune) == 1
    assert scheduled.count(app._run_startup_update_toast_check) == 0
    timers[0][3].stop.assert_called_once()
    assert app._startup_deferred_loads_released is True
    assert app._dirty_agents is False
    assert app._dirty_axe is False
    assert app._dirty_patches is False
    assert app._dirty_notifications is False


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
    assert scheduled.count(app._run_dismissed_named_procs_startup_prune) == 1


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
