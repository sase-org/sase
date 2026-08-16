"""Event-driven auto-refresh dirty flag tests."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.actions._event_refresh import AGENTS_LOAD_MIN_INTERVAL_SECONDS
from sase.ace.tui.actions.event_handlers import FULL_SANITY_REFRESH_SECONDS

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
@pytest.mark.parametrize("panel_mode_label", ["tools", "collapsed"])
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


@pytest.mark.asyncio
async def test_new_notification_schedules_agents_refresh_on_agents_tab() -> None:
    """Notification-triggered agent refreshes go through the debounce entry point."""
    app = _FakeApp(watcher_active=True)
    app._dirty_notifications = True
    app._poll_agent_completions_result = True

    await app._run_auto_refresh()

    assert app.refresh_calls == ["notifications", "request_agents:notification"]
    assert app.refresh_requests == ["notification"]
    assert app._dirty_notifications is False
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_new_notification_off_tab_falls_back_to_broad_when_unresolvable() -> None:
    """Notification targeting now runs regardless of tab.

    A completion whose agent cannot be resolved from cached state (no
    loaded roster match) still reaches the broad fallback even off-tab --
    the target is genuinely absent, so waiting for a tab switch would
    leave the row missing indefinitely.
    """
    app = _FakeApp(watcher_active=True)
    app.current_tab = "patches"
    app._dirty_notifications = True
    app._poll_agent_completions_result = True

    await app._run_auto_refresh()

    assert app.refresh_calls == ["notifications", "request_agents:notification"]
    assert app.refresh_requests == ["notification"]


@pytest.mark.asyncio
async def test_new_notification_off_tab_with_resolvable_agent_schedules_exact_delta(
    tmp_path: Path,
) -> None:
    """A completion for an already-loaded agent stays a bounded delta off-tab."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "patches"
    app._dirty_notifications = True
    app._poll_agent_completions_result = True

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    agent = _make_agent(
        status="DONE",
        cl_name="race-agent",
        raw_suffix="20260722090000",
        artifacts_dir=str(artifacts_dir),
    )
    # Folded/filtered off the visible `_agents` projection, but still in
    # the complete loaded roster.
    app._agents_with_children = [agent]  # type: ignore[attr-defined]
    app._notification_snapshot_cache = SimpleNamespace(  # type: ignore[attr-defined]
        notifications=[
            SimpleNamespace(
                sender="user-agent",
                action="JumpToAgent",
                dismissed=False,
                action_data={"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix},
            )
        ]
    )

    await app._run_auto_refresh()

    assert app.refresh_calls == ["notifications", "delta:notification:1"]
    assert app.delta_requests == [("notification", (artifacts_dir,))]
    assert app.refresh_requests == []


@pytest.mark.asyncio
async def test_new_notification_does_not_duplicate_due_agents_load() -> None:
    app = _FakeApp(watcher_active=True)
    app._dirty_notifications = True
    app._dirty_agents = True
    app._poll_agent_completions_result = True

    await app._run_auto_refresh()

    assert app.refresh_calls == ["notifications", "agents"]
    assert "schedule_agents" not in app.refresh_calls
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_watcher_inactive_runs_full_refresh() -> None:
    """Without a watcher the auto-refresh path keeps polling every surface."""
    app = _FakeApp(watcher_active=False)
    await app._run_auto_refresh()
    assert "axe" in app.refresh_calls
    assert "notifications" in app.refresh_calls
    assert "agents" in app.refresh_calls


@pytest.mark.asyncio
async def test_sanity_floor_forces_refresh_when_overdue() -> None:
    """A clean watcher state still reconciles once per sanity window."""
    app = _FakeApp(watcher_active=True)
    app._last_full_sanity_refresh = time.monotonic() - FULL_SANITY_REFRESH_SECONDS - 1.0
    await app._run_auto_refresh()
    assert "axe" in app.refresh_calls
    assert "agents" in app.refresh_calls


@pytest.mark.asyncio
async def test_off_tab_dirty_agents_does_not_load_and_keeps_flag_set() -> None:
    """Auto-refresh while off the agents tab leaves the loader untouched.

    The dirty flag must persist so the next eligible tick (tab switch or
    sanity floor) picks up the deferred load.
    """
    app = _FakeApp(watcher_active=True)
    app.current_tab = "patches"
    app._dirty_agents = True
    await app._run_auto_refresh()
    assert "agents" not in app.refresh_calls
    assert app._dirty_agents is True


@pytest.mark.asyncio
async def test_off_tab_sanity_tick_still_loads_agents() -> None:
    """Sanity-floor refresh runs the loader even when off the agents tab."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "patches"
    app._dirty_agents = True
    app._last_full_sanity_refresh = time.monotonic() - FULL_SANITY_REFRESH_SECONDS - 1.0
    await app._run_auto_refresh()
    assert "agents" in app.refresh_calls
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_off_tab_queued_delta_runs_without_tab_switch() -> None:
    """A bounded, already-queued artifact delta stays live off-tab.

    Broad loads remain tab-gated, but an exact delta is cheap and
    independent of which tab is on screen, so it must not wait for a tab
    switch or the sanity floor.
    """
    app = _FakeApp(watcher_active=True)
    app.current_tab = "patches"
    app._dirty_agents = True
    app._dirty_agent_artifact_dirs = (Path("/tmp/artifacts/a"),)

    await app._run_auto_refresh()

    assert app.refresh_calls == ["delta:watcher:1"]
    assert app.delta_requests == [("watcher", (Path("/tmp/artifacts/a"),))]
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_off_tab_delta_failure_retains_dirty_state_without_broad_load() -> None:
    """An off-tab delta that cannot be applied never escalates to a broad load.

    If the exact delta consumer is unavailable, the dirty state is left in
    place for the next Agents-tab entry or sanity pass instead of falling
    back to the expensive loader while off-tab.
    """
    app = _FakeApp(watcher_active=True)
    app.current_tab = "patches"
    app._dirty_agents = True
    app._dirty_agent_artifact_dirs = (Path("/tmp/artifacts/a"),)
    app._schedule_agent_artifact_delta_refresh = None  # type: ignore[assignment]

    await app._run_auto_refresh()

    assert "agents" not in app.refresh_calls
    assert app._dirty_agents is True
    assert app._dirty_agent_artifact_dirs == (Path("/tmp/artifacts/a"),)


@pytest.mark.asyncio
async def test_debounce_collapses_back_to_back_agent_loads() -> None:
    """Two auto-refresh ticks inside the debounce window only load once."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app._dirty_agents = True
    await app._run_auto_refresh()
    assert app.refresh_calls.count("agents") == 1
    app._dirty_agents = True
    await app._run_auto_refresh()
    assert app.refresh_calls.count("agents") == 1
    assert app._dirty_agents is True


@pytest.mark.asyncio
async def test_debounce_window_clears_after_interval() -> None:
    """Once the debounce window elapses, the next tick loads again."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app._dirty_agents = True
    await app._run_auto_refresh()
    assert app.refresh_calls.count("agents") == 1
    app._last_agents_load_mono = (
        time.monotonic() - AGENTS_LOAD_MIN_INTERVAL_SECONDS - 0.1
    )
    app._dirty_agents = True
    await app._run_auto_refresh()
    assert app.refresh_calls.count("agents") == 2


@pytest.mark.asyncio
async def test_debounce_bypassed_by_sanity_floor() -> None:
    """A sanity-due tick must run the loader even inside the debounce window."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app._dirty_agents = True
    app._last_agents_load_mono = time.monotonic()
    app._last_full_sanity_refresh = time.monotonic() - FULL_SANITY_REFRESH_SECONDS - 1.0
    await app._run_auto_refresh()
    assert "agents" in app.refresh_calls
