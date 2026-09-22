"""Event-driven auto-refresh debounce, trace, and surface-token tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from sase.ace.tui.actions._event_refresh import AGENTS_LOAD_MIN_INTERVAL_SECONDS
from sase.ace.tui.actions.event_handlers import FULL_SANITY_REFRESH_SECONDS
from sase.feature_flags import override_flags

from ._event_handlers_dirty_flags_helpers import _FakeApp, _surface_token_snapshot


@pytest.mark.asyncio
async def test_fallback_broad_load_covers_retained_exact_agent_delta() -> None:
    """Fallback refreshes must not throw away exact artifact dirs."""
    app = _FakeApp(watcher_active=True)
    artifact_dir = Path("/tmp/artifacts/a")
    app._dirty_agents = True
    app._dirty_agent_artifact_fallback_reason = "unknown_watcher_path"
    app._dirty_agent_artifact_dirs = (artifact_dir,)
    app._probed_surface_tokens = _surface_token_snapshot(agents=3)

    with override_flags(ace_refresh_tokens=True):
        await app._run_auto_refresh()

    assert app.refresh_calls == ["agents", "delta-load:watcher:1"]
    assert app.delta_load_requests == [("watcher", (artifact_dir,))]
    assert app._dirty_agents is False
    assert app._dirty_agent_artifact_dirs == ()
    assert app._dirty_agent_artifact_fallback_reason is None
    assert app._last_completed_surface_tokens["agents"] == (
        app._probed_surface_tokens.agents
    )


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


@pytest.mark.asyncio
async def test_auto_refresh_tick_emits_surface_reload_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Idle-diet per-tick counters land on the existing SASE_TUI_TRACE channel."""
    from sase.ace.tui.util import trace

    log = tmp_path / "tui_trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    trace._context.clear()

    app = _FakeApp(watcher_active=False)
    app._probed_surface_tokens = _surface_token_snapshot(axe=2)
    with override_flags(ace_refresh_tokens=True):
        await app._run_auto_refresh()

    trace._flush_trace_writes()
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    ticks = [row for row in rows if row.get("span") == "refresh.auto_tick"]
    assert len(ticks) == 1
    assert ticks[0]["surfaces_reloaded"] == 1
    assert ticks[0]["surfaces"] == "axe"
    assert ticks[0]["axe_file_opens"] == 0
    assert ticks[0]["fleet_attention_cache_polls"] == 0
    assert ticks[0]["fleet_attention_network_polls"] == 0
    assert ticks[0]["fleet_attention_changed"] == 0


@pytest.mark.asyncio
async def test_watcherless_matching_tokens_skip_refreshes() -> None:
    """Enabled tokens restore the dirty gate even without a watcher."""
    app = _FakeApp(watcher_active=False)
    with override_flags(ace_refresh_tokens=True):
        await app._run_auto_refresh()
    assert app.refresh_calls == []
    assert app.token_probe_calls == 1


@pytest.mark.asyncio
async def test_watcherless_token_drift_refreshes_only_that_surface() -> None:
    app = _FakeApp(watcher_active=False)
    app._probed_surface_tokens = _surface_token_snapshot(axe=2)
    with override_flags(ace_refresh_tokens=True):
        await app._run_auto_refresh()
    assert app.refresh_calls == ["axe"]
    assert app._last_completed_surface_tokens["axe"] == app._probed_surface_tokens.axe


@pytest.mark.asyncio
async def test_watcher_and_token_drift_both_refresh() -> None:
    """Token drift works even when the watcher is active and flags are clean."""
    app = _FakeApp(watcher_active=True)
    app._probed_surface_tokens = _surface_token_snapshot(notifications=9)
    with override_flags(ace_refresh_tokens=True):
        await app._run_auto_refresh()
    assert app.refresh_calls == ["notifications"]


@pytest.mark.asyncio
async def test_first_load_baselines_tokens_after_success() -> None:
    app = _FakeApp(watcher_active=False)
    app._last_completed_surface_tokens = {}
    with override_flags(ace_refresh_tokens=True):
        await app._run_auto_refresh()
    assert "axe" in app.refresh_calls
    assert "notifications" in app.refresh_calls
    assert "agents" in app.refresh_calls
    assert app._last_completed_surface_tokens["agents"] == (
        app._probed_surface_tokens.agents
    )


@pytest.mark.asyncio
async def test_off_tab_token_drift_keeps_old_agents_baseline() -> None:
    app = _FakeApp(watcher_active=False)
    app.current_tab = "patches"
    previous = app._last_completed_surface_tokens["agents"]
    app._probed_surface_tokens = _surface_token_snapshot(agents=4)
    with override_flags(ace_refresh_tokens=True):
        await app._run_auto_refresh()
    assert "agents" not in app.refresh_calls
    assert app._last_completed_surface_tokens["agents"] == previous


@pytest.mark.asyncio
async def test_debounced_token_drift_keeps_old_agents_baseline() -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app._dirty_agents = True
    await app._run_auto_refresh()
    previous = app._last_completed_surface_tokens["agents"]
    app._dirty_agents = True
    app._probed_surface_tokens = _surface_token_snapshot(agents=8)
    with override_flags(ace_refresh_tokens=True):
        await app._run_auto_refresh()
    assert app.refresh_calls.count("agents") == 1
    assert app._dirty_agents is True
    assert app._last_completed_surface_tokens["agents"] == previous


@pytest.mark.asyncio
async def test_exact_agent_delta_accepts_token_without_fallback() -> None:
    app = _FakeApp(watcher_active=True)
    app._dirty_agent_artifact_dirs = (Path("/tmp/artifacts/a"),)
    app._probed_surface_tokens = _surface_token_snapshot(agents=3)
    with override_flags(ace_refresh_tokens=True):
        await app._run_auto_refresh()
    assert app.refresh_calls == ["delta:watcher:1"]
    assert app._last_completed_surface_tokens["agents"] == (
        app._probed_surface_tokens.agents
    )


@pytest.mark.asyncio
async def test_token_probe_failure_fails_open() -> None:
    app = _FakeApp(watcher_active=False)
    app._probed_surface_tokens = _surface_token_snapshot(indeterminate="axe")
    previous = app._last_completed_surface_tokens["axe"]
    with override_flags(ace_refresh_tokens=True):
        await app._run_auto_refresh()
    assert "axe" in app.refresh_calls
    assert app._last_completed_surface_tokens["axe"] == previous


@pytest.mark.asyncio
async def test_token_churn_does_not_overlap_in_flight_agent_load() -> None:
    app = _FakeApp(watcher_active=False)
    app._last_completed_surface_tokens = {}
    app._agents_loading = True
    with override_flags(ace_refresh_tokens=True):
        await app._run_auto_refresh()
    assert "agents" not in app.refresh_calls
    assert app._last_completed_surface_tokens.get("agents") is None


@pytest.mark.asyncio
async def test_disabled_flag_preserves_watcherless_unconditional_refresh() -> None:
    app = _FakeApp(watcher_active=False)
    with override_flags(ace_refresh_tokens=False):
        await app._run_auto_refresh()
        app._last_agents_load_mono = (
            time.monotonic() - AGENTS_LOAD_MIN_INTERVAL_SECONDS - 0.1
        )
        await app._run_auto_refresh()
    assert app.refresh_calls.count("agents") == 2
    assert app.token_probe_calls == 0


@pytest.mark.asyncio
async def test_enabled_flag_baselines_after_first_load_then_skips() -> None:
    app = _FakeApp(watcher_active=False)
    app._last_completed_surface_tokens = {}
    with override_flags(ace_refresh_tokens=True):
        await app._run_auto_refresh()
        app.refresh_calls.clear()
        await app._run_auto_refresh()
    assert app.refresh_calls == []
    completed = app._last_completed_surface_tokens
    probed = app._probed_surface_tokens
    assert completed["agents"] == probed.agents
    assert completed["axe"] == probed.axe
    assert completed["notifications"] == probed.notifications
