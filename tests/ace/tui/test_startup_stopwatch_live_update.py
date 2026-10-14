"""Compatibility import path for ACE startup stopwatch tests.

The test cases live in focused private modules; tests with private helper imports or
monkeypatch targets stay here so their established paths remain unchanged.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.app import AceApp
from tests._notification_toasts_helpers import _FakeApp, _make, _patch_snapshot
from tests.ace.tui._startup_stopwatch_live_update_contracts import (
    test_first_paint_marker_precedes_non_frame_startup_services,
    test_on_mount_is_synchronous,
    test_on_mount_seeds_current_tab_in_trace_context,
    test_read_last_selection_name_delegates_to_loader,
    test_read_notifications_for_startup_uses_snapshot_tabs,
    test_read_patches_from_disk_returns_list,
    test_read_unread_notification_ids_returns_set,
)
from tests.ace.tui._startup_stopwatch_live_update_scheduling import (
    test_initial_artifacts_startup_releases_after_first_paint,
    test_initial_axe_startup_starts_axe_before_agents,
    test_slow_mount_state_read_does_not_block_app_key_dispatch,
    test_start_post_mount_background_loads_gates_axe_on_agents_ready,
    test_start_post_mount_background_loads_starts_visible_agents_first,
    test_startup_configures_periodic_update_interval_from_loaded_config,
    test_startup_fallback_releases_deferred_without_visible_ready,
    test_startup_tab_switch_does_not_duplicate_surface_load,
)
from tests.ace.tui._startup_stopwatch_live_update_stopwatch import (
    test_axe_first_load_path_no_longer_ends_stopwatch_directly,
    test_maybe_end_startup_stopwatch_clears_startup_window_flag,
    test_maybe_end_startup_stopwatch_gates_on_axe_when_axe_is_visible,
    test_maybe_end_startup_stopwatch_gates_on_visible_tab_only,
    test_maybe_end_startup_stopwatch_is_safe_when_called_repeatedly,
    test_old_three_second_mark_does_not_release_deferred_loads,
    test_stopwatch_ends_as_soon_as_visible_surface_finishes_first,
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


@pytest.mark.asyncio
async def test_auto_refresh_before_release_skips_heavy_surfaces() -> None:
    """A tick before release must not collect axe, load Agents, or reload Patches."""
    from tests.ace.tui._event_handlers_dirty_flags_helpers import _FakeApp

    app = _FakeApp(watcher_active=True)
    app._startup_deferred_loads_released = False
    app._last_full_sanity_refresh = 0.0
    app._dirty_axe = True
    app._dirty_agents = True
    app._dirty_patches = True
    app.current_tab = "agents"
    app._last_completed_surface_tokens = {}

    await app._run_auto_refresh()

    assert app.refresh_calls == []
    assert app.token_probe_calls == 1
    assert getattr(app, "_axe_first_load_done", False) is False
    assert "axe" in app._last_completed_surface_tokens
    assert "agents" not in app._last_completed_surface_tokens
    assert "patches" in app._last_completed_surface_tokens


@pytest.mark.asyncio
async def test_unpinned_first_tick_before_release_is_not_a_sanity_refresh() -> None:
    """The dirty-flags helper pins sanity time; an unpinned first tick still holds."""
    from tests.ace.tui._event_handlers_dirty_flags_helpers import _FakeApp

    app = _FakeApp(watcher_active=True)
    app._startup_deferred_loads_released = False
    app._last_full_sanity_refresh = 0.0
    app._dirty_axe = True
    app._dirty_agents = True
    app._dirty_patches = True

    await app._run_auto_refresh()

    assert "axe" not in app.refresh_calls
    assert "agents" not in app.refresh_calls
    assert "patches" not in app.refresh_calls
    assert app._last_full_sanity_refresh == 0.0


def test_release_preserves_agents_dirty_set_during_startup_load() -> None:
    """Watcher events during the startup Agents load survive release."""
    app = AceApp()
    app._mark_startup_on_mount()
    scheduled: list[object] = []

    with (
        patch.object(
            app,
            "run_worker",
            side_effect=lambda fn, **kwargs: scheduled.append(fn),
        ),
        patch.object(app, "set_timer", return_value=MagicMock()),
        patch.object(app, "set_interval", return_value=MagicMock()),
        patch.object(app, "_start_post_first_paint_services"),
        patch.object(app, "_start_artifact_watcher"),
        patch.object(app, "_start_prompt_source_watcher"),
        patch.object(app, "_maybe_show_post_update_toast", return_value=False),
        patch.object(app, "_schedule_link_index_refresh"),
        patch.object(app, "_schedule_deferred_startup_maintenance"),
        patch.object(app, "_flush_deferred_agents_post_roster_work"),
        patch.object(app, "_flush_deferred_monitor_reconcile"),
    ):
        app._start_post_mount_background_loads()
        assert app._dirty_agents is False
        app._dirty_agents = True
        app._release_startup_deferred_loads(reason="test")

    assert app._dirty_agents is True
    assert app._startup_deferred_loads_released is True


@pytest.mark.asyncio
async def test_agents_watcher_during_startup_load_refreshes_after_release() -> None:
    """A dirty Agents flag that survived the hold still reloads after release."""
    from tests.ace.tui._event_handlers_dirty_flags_helpers import _FakeApp

    app = _FakeApp(watcher_active=True)
    app._startup_deferred_loads_released = True
    app._dirty_agents = True
    app._dirty_axe = False
    app._dirty_patches = False
    app._dirty_notifications = False

    await app._run_auto_refresh()

    assert "agents" in app.refresh_calls


@pytest.mark.asyncio
async def test_agents_token_drift_during_hold_refreshes_after_release() -> None:
    """Hold ticks must not accept Agents tokens, so post-release drift reloads."""
    from tests.ace.tui._event_handlers_dirty_flags_helpers import (
        _FakeApp,
        _completed_tokens,
        _surface_token_snapshot,
    )

    baseline = _surface_token_snapshot(agents=1)
    drifted = _surface_token_snapshot(agents=2)
    app = _FakeApp(watcher_active=True)
    app._last_completed_surface_tokens = _completed_tokens(baseline)
    app._probed_surface_tokens = drifted
    app._startup_deferred_loads_released = False
    app._dirty_agents = False
    app._dirty_axe = False
    app._dirty_patches = False
    app._dirty_notifications = False

    await app._run_auto_refresh()

    assert app.refresh_calls == []
    assert app._last_completed_surface_tokens["agents"] == baseline.agents

    app._startup_deferred_loads_released = True
    await app._run_auto_refresh()

    assert "agents" in app.refresh_calls


@pytest.mark.asyncio
async def test_post_release_tick_does_not_reload_agents_when_unchanged() -> None:
    """No watcher event or token drift means the first post-release tick skips Agents."""
    from tests.ace.tui._event_handlers_dirty_flags_helpers import _FakeApp

    app = _FakeApp(watcher_active=True)
    app._startup_deferred_loads_released = True
    app._dirty_agents = False
    app._dirty_axe = False
    app._dirty_patches = False
    app._dirty_notifications = False

    await app._run_auto_refresh()

    assert "agents" not in app.refresh_calls


@pytest.mark.asyncio
async def test_startup_maintenance_jobs_run_strictly_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CPU-heavy maintenance starts one job after the previous in-flight flag clears."""
    from sase.ace.tui.actions import _startup_loads_maintenance as maintenance

    monkeypatch.setattr(maintenance, "_STARTUP_MAINTENANCE_POLL_SECONDS", 0.01)
    app = AceApp()
    order: list[str] = []
    catalog_started = asyncio.Event()
    catalog_done = asyncio.Event()
    link_started = asyncio.Event()

    def schedule_catalog(*, reason: str, **_kwargs: object) -> None:
        del reason
        order.append("catalog")
        app._prompt_catalog_rebuild_in_flight = True
        catalog_started.set()

        async def _finish() -> None:
            await catalog_done.wait()
            app._prompt_catalog_rebuild_in_flight = False
            app._prompt_catalog = object()

        asyncio.create_task(_finish())

    def schedule_link(*, source: str) -> None:
        del source
        order.append("link")
        link_started.set()
        app._link_index_loading = False
        app._link_index = object()

    def schedule_toast() -> None:
        order.append("toast")
        app._automatic_update_check_timer = object()

    def schedule_usage() -> None:
        order.append("usage")
        app._usage_refresh_fallback_started = True
        app._usage_refresh_fallback_first_request_done = True

    def schedule_prompt_bar() -> None:
        order.append("prompt_bar")
        app._prompt_bar_import_warm_done = True

    monkeypatch.setattr(app, "_schedule_prompt_catalog_rebuild", schedule_catalog)
    monkeypatch.setattr(app, "_schedule_link_index_refresh", schedule_link)
    monkeypatch.setattr(app, "_schedule_startup_update_toast_check", schedule_toast)
    monkeypatch.setattr(app, "_schedule_usage_refresh_fallback", schedule_usage)
    monkeypatch.setattr(app, "_schedule_prompt_bar_import_warm", schedule_prompt_bar)

    task = asyncio.create_task(
        app._run_deferred_startup_maintenance_chain(reason="visible_ready")
    )
    await asyncio.wait_for(catalog_started.wait(), timeout=1.0)
    assert order == ["catalog"]
    assert not link_started.is_set()
    catalog_done.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert order == ["catalog", "link", "toast", "usage", "prompt_bar"]


@pytest.mark.asyncio
async def test_startup_maintenance_stuck_step_times_out_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stuck in-flight step hits the 20 s cap and the chain continues."""
    from sase.ace.tui.actions import _startup_loads_maintenance as maintenance

    monkeypatch.setattr(maintenance, "_STARTUP_MAINTENANCE_STEP_CAP_SECONDS", 0.05)
    monkeypatch.setattr(maintenance, "_STARTUP_MAINTENANCE_POLL_SECONDS", 0.01)
    app = AceApp()
    order: list[str] = []
    app._prompt_catalog_rebuild_in_flight = True

    def schedule_link(*, source: str) -> None:
        del source
        order.append("link")
        app._link_index = object()

    monkeypatch.setattr(
        app,
        "_schedule_prompt_catalog_rebuild",
        lambda **_kwargs: order.append("catalog"),
    )
    monkeypatch.setattr(app, "_schedule_link_index_refresh", schedule_link)
    monkeypatch.setattr(
        app,
        "_schedule_startup_update_toast_check",
        lambda: order.append("toast"),
    )
    monkeypatch.setattr(
        app,
        "_schedule_usage_refresh_fallback",
        lambda: order.append("usage"),
    )
    monkeypatch.setattr(
        app,
        "_schedule_prompt_bar_import_warm",
        lambda: order.append("prompt_bar"),
    )

    await asyncio.wait_for(
        app._run_deferred_startup_maintenance_chain(reason="fallback"),
        timeout=1.0,
    )
    assert "catalog" not in order
    assert order == ["link", "toast", "usage", "prompt_bar"]
