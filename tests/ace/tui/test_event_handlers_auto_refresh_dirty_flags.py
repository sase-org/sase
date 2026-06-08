"""Event-driven auto-refresh dirty flag tests."""

from __future__ import annotations

import time

import pytest

from sase.ace.tui.actions._event_refresh import AGENTS_LOAD_MIN_INTERVAL_SECONDS
from sase.ace.tui.actions.event_handlers import FULL_SANITY_REFRESH_SECONDS

from ._event_handlers_dirty_flags_helpers import _FakeApp, _make_agent


@pytest.mark.asyncio
async def test_watcher_active_clean_flags_skip_all_refreshes() -> None:
    """Watcher active + every dirty flag clear + sanity-floor not due -> no work."""
    app = _FakeApp(watcher_active=True)
    await app._on_auto_refresh()
    assert app.refresh_calls == []


@pytest.mark.asyncio
async def test_watcher_active_clean_agents_tick_refreshes_selected_file_only() -> None:
    """Clean Agents-tab ticks refresh the selected live diff, not the loader."""
    app = _FakeApp(watcher_active=True)
    agent = _make_agent()
    app._agents = [agent]

    await app._on_auto_refresh()

    assert app.refresh_calls == ["file"]
    assert app.agent_detail.refreshed_agents == [agent]
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_watcher_active_clean_tick_skips_completed_selected_agent() -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent(status="DONE")]

    await app._on_auto_refresh()

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

    await app._on_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
async def test_watcher_active_clean_tick_skips_attempt_pinned_detail() -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    app.current_attempt_number = 1

    await app._on_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag_name",
    ["_hint_mode_active", "_entry_jump_mode_active", "_accept_mode_active"],
)
async def test_watcher_active_clean_tick_skips_file_refresh_in_transient_modes(
    flag_name: str,
) -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    setattr(app, flag_name, True)

    await app._on_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
async def test_watcher_active_clean_tick_skips_file_refresh_while_loader_runs() -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    app._agents_loading = True

    await app._on_auto_refresh()

    assert app.refresh_calls == []
    assert app.agent_detail.refreshed_agents == []


@pytest.mark.asyncio
async def test_watcher_active_dirty_agents_load_does_not_refresh_file_panel() -> None:
    app = _FakeApp(watcher_active=True)
    app._agents = [_make_agent()]
    app._dirty_agents = True

    await app._on_auto_refresh()

    assert app.refresh_calls == ["agents"]
    assert app.agent_detail.refreshed_agents == []
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_watcher_active_dirty_agents_runs_only_agent_path() -> None:
    """Only flag-set surfaces refresh when the watcher is active."""
    app = _FakeApp(watcher_active=True)
    app._dirty_agents = True
    await app._on_auto_refresh()
    assert "axe" not in app.refresh_calls
    assert "notifications" not in app.refresh_calls
    assert "agents" in app.refresh_calls
    assert "changespecs" not in app.refresh_calls
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_watcher_active_dirty_notifications_polls_completions() -> None:
    """``_dirty_notifications`` gates the on-disk notification snapshot poll."""
    app = _FakeApp(watcher_active=True)
    app._dirty_notifications = True
    await app._on_auto_refresh()
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

    await app._on_auto_refresh()

    assert app.refresh_calls == ["notifications", "request_agents:notification"]
    assert app.refresh_requests == ["notification"]
    assert app._dirty_notifications is False
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_new_notification_does_not_schedule_agents_refresh_off_tab() -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "changespecs"
    app._dirty_notifications = True
    app._poll_agent_completions_result = True

    await app._on_auto_refresh()

    assert app.refresh_calls == ["notifications"]


@pytest.mark.asyncio
async def test_new_notification_does_not_duplicate_due_agents_load() -> None:
    app = _FakeApp(watcher_active=True)
    app._dirty_notifications = True
    app._dirty_agents = True
    app._poll_agent_completions_result = True

    await app._on_auto_refresh()

    assert app.refresh_calls == ["notifications", "agents"]
    assert "schedule_agents" not in app.refresh_calls
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_watcher_inactive_runs_full_refresh() -> None:
    """Without a watcher the auto-refresh path keeps polling every surface."""
    app = _FakeApp(watcher_active=False)
    await app._on_auto_refresh()
    assert "axe" in app.refresh_calls
    assert "notifications" in app.refresh_calls
    assert "agents" in app.refresh_calls


@pytest.mark.asyncio
async def test_sanity_floor_forces_refresh_when_overdue() -> None:
    """A clean watcher state still reconciles once per sanity window."""
    app = _FakeApp(watcher_active=True)
    app._last_full_sanity_refresh = time.monotonic() - FULL_SANITY_REFRESH_SECONDS - 1.0
    await app._on_auto_refresh()
    assert "axe" in app.refresh_calls
    assert "agents" in app.refresh_calls


@pytest.mark.asyncio
async def test_off_tab_dirty_agents_does_not_load_and_keeps_flag_set() -> None:
    """Auto-refresh while off the agents tab leaves the loader untouched.

    The dirty flag must persist so the next eligible tick (tab switch or
    sanity floor) picks up the deferred load.
    """
    app = _FakeApp(watcher_active=True)
    app.current_tab = "changespecs"
    app._dirty_agents = True
    await app._on_auto_refresh()
    assert "agents" not in app.refresh_calls
    assert app._dirty_agents is True


@pytest.mark.asyncio
async def test_off_tab_sanity_tick_still_loads_agents() -> None:
    """Sanity-floor refresh runs the loader even when off the agents tab."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "changespecs"
    app._dirty_agents = True
    app._last_full_sanity_refresh = time.monotonic() - FULL_SANITY_REFRESH_SECONDS - 1.0
    await app._on_auto_refresh()
    assert "agents" in app.refresh_calls
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_debounce_collapses_back_to_back_agent_loads() -> None:
    """Two auto-refresh ticks inside the debounce window only load once."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app._dirty_agents = True
    await app._on_auto_refresh()
    assert app.refresh_calls.count("agents") == 1
    app._dirty_agents = True
    await app._on_auto_refresh()
    assert app.refresh_calls.count("agents") == 1
    assert app._dirty_agents is True


@pytest.mark.asyncio
async def test_debounce_window_clears_after_interval() -> None:
    """Once the debounce window elapses, the next tick loads again."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app._dirty_agents = True
    await app._on_auto_refresh()
    assert app.refresh_calls.count("agents") == 1
    app._last_agents_load_mono = (
        time.monotonic() - AGENTS_LOAD_MIN_INTERVAL_SECONDS - 0.1
    )
    app._dirty_agents = True
    await app._on_auto_refresh()
    assert app.refresh_calls.count("agents") == 2


@pytest.mark.asyncio
async def test_debounce_bypassed_by_sanity_floor() -> None:
    """A sanity-due tick must run the loader even inside the debounce window."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app._dirty_agents = True
    app._last_agents_load_mono = time.monotonic()
    app._last_full_sanity_refresh = time.monotonic() - FULL_SANITY_REFRESH_SECONDS - 1.0
    await app._on_auto_refresh()
    assert "agents" in app.refresh_calls
