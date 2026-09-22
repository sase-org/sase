"""Event-driven auto-refresh clean-tick and file-panel tests."""

from __future__ import annotations

import asyncio
import threading

import pytest

from sase.ace.tui.actions.event_refresh._freshness import surface_refreshed_age

from ._event_handlers_dirty_flags_helpers import _FakeApp, _make_agent


@pytest.mark.asyncio
async def test_auto_refresh_task_keeps_loop_live_and_coalesces_ticks() -> None:
    """Slow auto-refresh I/O cannot occupy the pump; tick bursts trail once."""
    app = _FakeApp(watcher_active=True)
    app._dirty_agents = True
    entered = threading.Event()
    release = threading.Event()
    load_calls = 0

    async def _slow_load_agents_async() -> None:
        nonlocal load_calls
        load_calls += 1
        entered.set()
        await asyncio.to_thread(release.wait, 1.0)

    app._load_agents_async = _slow_load_agents_async  # type: ignore[method-assign]
    try:
        app._on_auto_refresh()
        await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=0.5)

        for _ in range(5):
            app._on_auto_refresh()
        assert app._auto_refresh_pending is True

        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=0.05)
    finally:
        release.set()
        while tasks := list(getattr(app, "_pump_free_async_tasks", ())):
            await asyncio.gather(*tasks)
            await asyncio.sleep(0)

    # The dirty work ran once. All overlapping ticks collapsed into one clean
    # follow-up pass rather than stacking more agent loads.
    assert load_calls == 1
    assert app._auto_refresh_pending is False


@pytest.mark.asyncio
async def test_watcher_active_clean_flags_skip_all_refreshes() -> None:
    """Watcher active + every dirty flag clear + sanity-floor not due -> no work."""
    app = _FakeApp(watcher_active=True)
    await app._run_auto_refresh()
    assert app.refresh_calls == []


@pytest.mark.asyncio
async def test_watcher_active_clean_agents_tick_refreshes_selected_file_only() -> None:
    """Clean Agents-tab ticks refresh the selected live diff, not the loader."""
    app = _FakeApp(watcher_active=True)
    agent = _make_agent()
    app._agents = [agent]

    await app._run_auto_refresh()

    assert app.refresh_calls == ["file"]
    assert app.agent_detail.refreshed_agents == [agent]
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_watcher_active_clean_tick_skips_completed_selected_agent() -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent(status="DONE")]

    await app._run_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
@pytest.mark.parametrize("panel_mode_label", ["tools", "none"])
async def test_watcher_active_clean_tick_skips_non_file_detail_modes(
    panel_mode_label: str,
) -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    app.agent_detail.panel_mode_label = panel_mode_label

    await app._run_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
async def test_watcher_active_clean_tick_skips_attempt_pinned_detail() -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    app.current_attempt_number = 1

    await app._run_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag_name",
    [
        "_hint_mode_active",
        "_entry_jump_mode_active",
        "_panel_fold_hint_mode_active",
        "_accept_mode_active",
    ],
)
async def test_watcher_active_clean_tick_skips_file_refresh_in_transient_modes(
    flag_name: str,
) -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    setattr(app, flag_name, True)

    await app._run_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
async def test_watcher_active_clean_tick_skips_file_refresh_while_loader_runs() -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    app._agents_loading = True

    await app._run_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
async def test_watcher_active_dirty_agents_load_does_not_refresh_file_panel() -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    app._dirty_agents = True

    await app._run_auto_refresh()

    assert app.refresh_calls == ["agents"]
    assert app.agent_detail.refreshed_agents == []
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_watcher_active_dirty_agents_runs_only_agent_path() -> None:
    """Only flag-set surfaces refresh when the watcher is active."""
    app = _FakeApp(watcher_active=True)
    app._dirty_agents = True
    await app._run_auto_refresh()
    assert "axe" not in app.refresh_calls
    assert "notifications" not in app.refresh_calls
    assert "agents" in app.refresh_calls
    assert "patches" not in app.refresh_calls
    assert app._dirty_agents is False
    assert surface_refreshed_age(app, "agents") is not None
    assert surface_refreshed_age(app, "axe") is None


@pytest.mark.asyncio
async def test_watcher_active_dirty_notifications_polls_completions() -> None:
    """``_dirty_notifications`` gates the on-disk notification snapshot poll."""
    app = _FakeApp(watcher_active=True)
    app._dirty_notifications = True
    await app._run_auto_refresh()
    assert "notifications" in app.refresh_calls
    assert "agents" not in app.refresh_calls
    assert "axe" not in app.refresh_calls
    assert app._dirty_notifications is False
