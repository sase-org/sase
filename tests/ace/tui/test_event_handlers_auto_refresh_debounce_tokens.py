"""Event-driven auto-refresh debounce, trace, and surface-token tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from sase.ace.tui.actions._event_refresh import AGENTS_LOAD_MIN_INTERVAL_SECONDS
from sase.ace.tui.actions.event_handlers import FULL_SANITY_REFRESH_SECONDS

from ._event_handlers_dirty_flags_helpers import (
    _FakeApp,
    _axe_kinded_snapshot,
    _completed_tokens,
    _surface_token_snapshot,
)


@pytest.mark.asyncio
async def test_fallback_broad_load_covers_retained_exact_agent_delta() -> None:
    """Fallback refreshes must not throw away exact artifact dirs."""
    app = _FakeApp(watcher_active=True)
    artifact_dir = Path("/tmp/artifacts/a")
    app._dirty_agents = True
    app._dirty_agent_artifact_fallback_reason = "unknown_watcher_path"
    app._dirty_agent_artifact_dirs = (artifact_dir,)
    app._probed_surface_tokens = _surface_token_snapshot(agents=3)

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
    assert ticks[0]["sanity_due"] is False
    assert ticks[0]["surface_reasons"]["axe"] == "token_drift"
    assert ticks[0]["surface_outcomes"]["axe"] == "applied_changed"
    assert ticks[0]["token_change_kinds"]["axe"] == ["content"]
    assert ticks[0]["consumer_token_drifted"]["axe"] is True
    assert ticks[0]["consumer_token_change_kinds"]["axe"] == ["content"]

    watcher_rows = [row for row in rows if row.get("event") == "refresh.watcher_stats"]
    assert {row["watcher_source"] for row in watcher_rows} == {
        "artifact",
        "prompt_source",
    }
    assert all(row["watcher_active"] is False for row in watcher_rows)


@pytest.mark.asyncio
async def test_auto_refresh_trace_records_unknown_even_when_sanity_is_due(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.util import trace

    log = tmp_path / "tui_trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    trace._context.clear()

    app = _FakeApp(watcher_active=False)
    app._probed_surface_tokens = _surface_token_snapshot(
        axe=2,
        indeterminate="axe",
    )
    app._last_full_sanity_refresh = time.monotonic() - FULL_SANITY_REFRESH_SECONDS - 1
    await app._run_auto_refresh()

    trace._flush_trace_writes()
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    ticks = [row for row in rows if row.get("span") == "refresh.auto_tick"]
    assert len(ticks) == 1
    assert ticks[0]["sanity_due"] is True
    assert ticks[0]["surface_reasons"]["axe"] == "sanity"
    assert ticks[0]["surface_outcomes"]["axe"] == "applied_changed"
    assert ticks[0]["consumer_token_drifted"]["axe"] is True
    assert ticks[0]["token_unknown_surfaces"] == ["axe"]


def test_watcher_trace_samples_deltas_and_instance_resets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.event_refresh import _watcher as watcher_module
    from sase.ace.tui.util import trace

    class FakeWatcher:
        def __init__(self, **stats: int) -> None:
            self.values = stats

        def stats(self) -> dict[str, int]:
            return dict(self.values)

    now = [100.0]
    monkeypatch.setattr(watcher_module.time, "monotonic", lambda: now[0])
    log = tmp_path / "watcher_trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    trace._context.clear()

    app = _FakeApp(watcher_active=False)
    first = FakeWatcher(inotify_readable_wakeups=1, queued_dispatches=1)
    app._fs_watcher = first
    app._sample_watcher_stats_for_trace()
    first.values["inotify_readable_wakeups"] = 3
    first.values["queued_dispatches"] = 2
    first.values["ui_dispatches"] = 1
    now[0] += 10.0
    app._sample_watcher_stats_for_trace()

    app._fs_watcher = FakeWatcher(inotify_readable_wakeups=4)
    now[0] += 10.0
    app._sample_watcher_stats_for_trace()
    trace._flush_trace_writes()

    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    artifact_rows = [
        row
        for row in rows
        if row.get("event") == "refresh.watcher_stats"
        and row.get("watcher_source") == "artifact"
    ]
    assert len(artifact_rows) == 3
    assert artifact_rows[0]["baseline_only"] is True
    assert artifact_rows[1]["interval_seconds"] == 10.0
    assert artifact_rows[1]["counter_deltas"]["inotify_readable_wakeups"] == 2
    assert artifact_rows[1]["counter_deltas"]["queued_dispatches"] == 1
    assert artifact_rows[1]["counter_deltas"]["ui_dispatches"] == 1
    assert artifact_rows[2]["instance_changed"] is True
    assert artifact_rows[2]["baseline_only"] is True
    assert artifact_rows[2]["counter_deltas"]["inotify_readable_wakeups"] == 0


@pytest.mark.asyncio
async def test_watcherless_matching_tokens_skip_refreshes() -> None:
    """Stat-only tokens restore the dirty gate even without a watcher."""
    app = _FakeApp(watcher_active=False)
    await app._run_auto_refresh()
    assert app.refresh_calls == []
    assert app.axe_load_kwargs == []
    assert app.token_probe_calls == 1


@pytest.mark.asyncio
async def test_sanity_before_services_visit_stays_header_only() -> None:
    """A hidden, never-visited Services tab must not walk chop snapshots."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app._axe_services_visited = False
    app._last_full_sanity_refresh = time.monotonic() - FULL_SANITY_REFRESH_SECONDS - 1.0
    await app._run_auto_refresh()
    assert "axe" in app.refresh_calls
    assert app.axe_load_kwargs[-1]["include_full_snapshots"] is False
    assert app.axe_load_kwargs[-1]["tail_all_chop_logs"] is False


@pytest.mark.asyncio
async def test_sanity_after_services_visit_collects_full_snapshots() -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app._axe_services_visited = True
    app._last_full_sanity_refresh = time.monotonic() - FULL_SANITY_REFRESH_SECONDS - 1.0
    await app._run_auto_refresh()
    assert "axe" in app.refresh_calls
    assert app.axe_load_kwargs[-1]["include_full_snapshots"] is True
    assert app.axe_load_kwargs[-1]["tail_all_chop_logs"] is True


@pytest.mark.asyncio
async def test_watcherless_token_drift_refreshes_only_that_surface() -> None:
    app = _FakeApp(watcher_active=False)
    app._probed_surface_tokens = _surface_token_snapshot(axe=2)
    await app._run_auto_refresh()
    assert app.refresh_calls == ["axe"]
    assert app._last_completed_surface_tokens["axe"] == app._probed_surface_tokens.axe


@pytest.mark.asyncio
async def test_watcher_and_token_drift_both_refresh() -> None:
    """Token drift works even when the watcher is active and flags are clean."""
    app = _FakeApp(watcher_active=True)
    app._probed_surface_tokens = _surface_token_snapshot(notifications=9)
    await app._run_auto_refresh()
    assert app.refresh_calls == ["notifications"]


@pytest.mark.asyncio
async def test_first_load_baselines_tokens_after_success() -> None:
    app = _FakeApp(watcher_active=False)
    app._last_completed_surface_tokens = {}
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
    await app._run_auto_refresh()
    assert app.refresh_calls.count("agents") == 1
    assert app._dirty_agents is True
    assert app._last_completed_surface_tokens["agents"] == previous


@pytest.mark.asyncio
async def test_exact_agent_delta_accepts_token_without_fallback() -> None:
    app = _FakeApp(watcher_active=True)
    app._dirty_agent_artifact_dirs = (Path("/tmp/artifacts/a"),)
    app._probed_surface_tokens = _surface_token_snapshot(agents=3)
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
    await app._run_auto_refresh()
    assert "axe" in app.refresh_calls
    assert app._last_completed_surface_tokens["axe"] == previous


@pytest.mark.asyncio
async def test_token_churn_does_not_overlap_in_flight_agent_load() -> None:
    app = _FakeApp(watcher_active=False)
    app._last_completed_surface_tokens = {}
    app._agents_loading = True
    await app._run_auto_refresh()
    assert "agents" not in app.refresh_calls
    assert app._last_completed_surface_tokens.get("agents") is None


@pytest.mark.asyncio
async def test_baselines_after_first_load_then_skips() -> None:
    app = _FakeApp(watcher_active=False)
    app._last_completed_surface_tokens = {}
    await app._run_auto_refresh()
    app.refresh_calls.clear()
    await app._run_auto_refresh()
    assert app.refresh_calls == []
    completed = app._last_completed_surface_tokens
    probed = app._probed_surface_tokens
    assert completed["agents"] == probed.agents
    assert completed["axe"] == probed.axe
    assert completed["notifications"] == probed.notifications


def _seed_kinded(app: _FakeApp, snapshot) -> None:
    app._probed_surface_tokens = snapshot
    app._last_completed_surface_tokens = _completed_tokens(snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize("watcher_active", [True, False])
async def test_axe_log_only_drift_skips_on_agents_tab(watcher_active: bool) -> None:
    """Heartbeat log growth is unconsumed while Services is hidden."""
    app = _FakeApp(watcher_active=watcher_active)
    app.current_tab = "agents"
    _seed_kinded(app, _axe_kinded_snapshot())
    previous = app._last_completed_surface_tokens["axe"]
    app._dirty_axe = True
    app._probed_surface_tokens = _axe_kinded_snapshot(log=9)

    await app._run_auto_refresh()

    assert "axe" not in app.refresh_calls
    assert app.axe_load_kwargs == []
    assert app._dirty_axe is False
    assert app._last_completed_surface_tokens["axe"] == previous


@pytest.mark.asyncio
async def test_axe_log_only_drift_reloads_on_services_tab() -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "services"
    app._axe_services_visited = True
    _seed_kinded(app, _axe_kinded_snapshot())
    app._probed_surface_tokens = _axe_kinded_snapshot(log=9)

    await app._run_auto_refresh()

    assert "axe" in app.refresh_calls
    assert app._last_completed_surface_tokens["axe"] == app._probed_surface_tokens.axe


@pytest.mark.asyncio
async def test_axe_status_only_drift_skips_on_agents_tab() -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    _seed_kinded(app, _axe_kinded_snapshot())
    previous = app._last_completed_surface_tokens["axe"]
    app._probed_surface_tokens = _axe_kinded_snapshot(status=4)

    await app._run_auto_refresh()

    assert "axe" not in app.refresh_calls
    assert app._last_completed_surface_tokens["axe"] == previous


@pytest.mark.asyncio
async def test_axe_pid_drift_reloads_on_agents_tab() -> None:
    app = _FakeApp(watcher_active=False)
    app.current_tab = "agents"
    _seed_kinded(app, _axe_kinded_snapshot())
    app._probed_surface_tokens = _axe_kinded_snapshot(pid=7)

    await app._run_auto_refresh()

    assert app.refresh_calls == ["axe"]
    assert app._last_completed_surface_tokens["axe"] == app._probed_surface_tokens.axe


@pytest.mark.asyncio
async def test_axe_service_drift_reloads_on_agents_tab() -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    _seed_kinded(app, _axe_kinded_snapshot())
    app._probed_surface_tokens = _axe_kinded_snapshot(service=3)

    await app._run_auto_refresh()

    assert "axe" in app.refresh_calls


@pytest.mark.asyncio
async def test_tab_switch_to_services_sees_pending_log_drift() -> None:
    """Skipped off-tab log drift remains observable after a Services visit."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    _seed_kinded(app, _axe_kinded_snapshot())
    app._probed_surface_tokens = _axe_kinded_snapshot(log=5)
    await app._run_auto_refresh()
    assert "axe" not in app.refresh_calls

    app.current_tab = "services"
    app._axe_services_visited = True
    await app._run_auto_refresh()
    assert "axe" in app.refresh_calls


@pytest.mark.asyncio
async def test_agents_index_only_skips_with_watcher() -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    _seed_kinded(app, _axe_kinded_snapshot())
    previous = app._last_completed_surface_tokens["agents"]
    bumped: list[str] = []
    app._bump_agents_capacity_generation = lambda: bumped.append("capacity")
    app._probed_surface_tokens = _axe_kinded_snapshot(index=4)

    await app._run_auto_refresh()

    assert "agents" not in app.refresh_calls
    assert bumped == []
    assert app._last_completed_surface_tokens["agents"] == previous


@pytest.mark.asyncio
async def test_agents_index_only_loads_without_watcher() -> None:
    app = _FakeApp(watcher_active=False)
    app.current_tab = "agents"
    _seed_kinded(app, _axe_kinded_snapshot())
    bumped: list[str] = []
    app._bump_agents_capacity_generation = lambda: bumped.append("capacity")
    app._probed_surface_tokens = _axe_kinded_snapshot(index=4)

    await app._run_auto_refresh()

    assert "agents" in app.refresh_calls
    assert bumped == ["capacity"]
    assert app._last_completed_surface_tokens["agents"] == (
        app._probed_surface_tokens.agents
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["artifacts", "membership"])
async def test_agents_non_index_drift_loads_with_watcher(field: str) -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    _seed_kinded(app, _axe_kinded_snapshot())
    app._probed_surface_tokens = _axe_kinded_snapshot(**{field: 8})

    await app._run_auto_refresh()

    assert "agents" in app.refresh_calls


@pytest.mark.asyncio
async def test_agents_pulse_only_skips_with_watcher() -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    _seed_kinded(app, _axe_kinded_snapshot())
    previous = app._last_completed_surface_tokens["agents"]
    bumped: list[str] = []
    app._bump_agents_capacity_generation = lambda: bumped.append("capacity")
    app._probed_surface_tokens = _axe_kinded_snapshot(pulse=8)

    await app._run_auto_refresh()

    assert "agents" not in app.refresh_calls
    assert bumped == []
    assert app._last_completed_surface_tokens["agents"] == previous


@pytest.mark.asyncio
async def test_agents_pulse_only_loads_without_watcher() -> None:
    app = _FakeApp(watcher_active=False)
    app.current_tab = "agents"
    _seed_kinded(app, _axe_kinded_snapshot())
    bumped: list[str] = []
    app._bump_agents_capacity_generation = lambda: bumped.append("capacity")
    app._probed_surface_tokens = _axe_kinded_snapshot(pulse=8)

    await app._run_auto_refresh()

    assert "agents" in app.refresh_calls
    assert bumped == ["capacity"]
    assert app._last_completed_surface_tokens["agents"] == (
        app._probed_surface_tokens.agents
    )


@pytest.mark.asyncio
async def test_agents_index_and_pulse_skip_with_watcher() -> None:
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    _seed_kinded(app, _axe_kinded_snapshot())
    previous = app._last_completed_surface_tokens["agents"]
    app._probed_surface_tokens = _axe_kinded_snapshot(index=4, pulse=8)

    await app._run_auto_refresh()

    assert "agents" not in app.refresh_calls
    assert app._last_completed_surface_tokens["agents"] == previous


@pytest.mark.asyncio
async def test_watcher_dirty_agents_still_loads_when_index_also_drifted() -> None:
    """Exact watcher deltas stay live; index skip only applies when flags are clean."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    _seed_kinded(app, _axe_kinded_snapshot())
    app._dirty_agents = True
    app._probed_surface_tokens = _axe_kinded_snapshot(index=4)

    await app._run_auto_refresh()

    assert "agents" in app.refresh_calls


@pytest.mark.asyncio
async def test_axe_apply_skip_accepts_token_without_counting_reload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bounded collect whose consumer projection is unchanged is not a reload."""
    from sase.ace.tui.util import trace

    log = tmp_path / "tui_trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    trace._context.clear()

    app = _FakeApp(watcher_active=True)
    app.current_tab = "services"
    app._axe_services_visited = True
    _seed_kinded(app, _axe_kinded_snapshot())
    app._probed_surface_tokens = _axe_kinded_snapshot(log=6)

    async def _load_axe_status_async(
        *,
        include_full_snapshots: bool | None = None,
        tail_all_chop_logs: bool = False,
    ) -> None:
        app.axe_load_kwargs.append(
            {
                "include_full_snapshots": include_full_snapshots,
                "tail_all_chop_logs": tail_all_chop_logs,
            }
        )
        app._axe_last_apply_skipped = True

    app._load_axe_status_async = _load_axe_status_async  # type: ignore[method-assign]

    await app._run_auto_refresh()

    assert app.axe_load_kwargs
    assert "axe" not in app.refresh_calls
    assert app._last_completed_surface_tokens["axe"] == app._probed_surface_tokens.axe
    trace._flush_trace_writes()
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    ticks = [row for row in rows if row.get("span") == "refresh.auto_tick"]
    assert len(ticks) == 1
    assert ticks[0]["surfaces_reloaded"] == 0
    assert ticks[0]["surfaces"] == ""


@pytest.mark.asyncio
async def test_sanity_floor_reloads_axe_despite_detail_only_drift() -> None:
    """Configured ``-s`` deadlines still force axe collect on the Agents tab."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "agents"
    app.sanity_refresh_interval = 120
    _seed_kinded(app, _axe_kinded_snapshot())
    app._probed_surface_tokens = _axe_kinded_snapshot(log=9)
    app._last_full_sanity_refresh = time.monotonic() - 121.0

    await app._run_auto_refresh()

    assert "axe" in app.refresh_calls
    assert "agents" in app.refresh_calls


@pytest.mark.asyncio
async def test_disabled_auto_refresh_interval_still_honors_skip_gates() -> None:
    """``-r 0`` does not start the timer; a stray tick still skips unchanged work."""
    app = _FakeApp(watcher_active=True)
    app.refresh_interval = 0
    _seed_kinded(app, _axe_kinded_snapshot())
    await app._run_auto_refresh()
    assert app.refresh_calls == []
    assert app.axe_load_kwargs == []
