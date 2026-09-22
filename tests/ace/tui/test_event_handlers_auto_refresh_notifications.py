"""Event-driven auto-refresh notification and off-tab gating tests."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.event_handlers import FULL_SANITY_REFRESH_SECONDS
from sase.feature_flags import override_flags

from ._event_handlers_dirty_flags_helpers import _FakeApp, _make_agent


@pytest.mark.asyncio
async def test_remote_attention_inventory_change_schedules_notifications_off_tab() -> (
    None
):
    """Global remote decisions update the badge without blocking the local tick."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "artifacts"
    cache_only_values: list[bool] = []

    async def poll_attention_inventory(*, source: str, cache_only: bool) -> bool:
        cache_only_values.append(cache_only)
        app.refresh_calls.append(f"attention:{source}")
        return True

    app._poll_fleet_attention_inventory = poll_attention_inventory  # type: ignore[attr-defined]

    await app._run_auto_refresh()

    assert app.refresh_calls == []
    assert cache_only_values == []
    await asyncio.gather(*tuple(app._pump_free_async_tasks))
    assert app.refresh_calls == ["attention:auto_refresh"]
    assert cache_only_values == [True]
    assert app._dirty_notifications is True

    await app._run_auto_refresh()

    assert app.refresh_calls == ["attention:auto_refresh", "notifications"]
    assert app._dirty_notifications is False


@pytest.mark.asyncio
async def test_blocked_attention_cache_poll_does_not_delay_agents_refresh() -> None:
    """A blocked attention cache poll cannot hold the Agents local surface hostage."""
    app = _FakeApp(watcher_active=True)
    app._dirty_agents = True
    entered = asyncio.Event()
    release = asyncio.Event()

    async def poll_attention_inventory(*, source: str, cache_only: bool) -> bool:
        del source
        assert cache_only is True
        entered.set()
        await release.wait()
        return False

    app._poll_fleet_attention_inventory = poll_attention_inventory  # type: ignore[attr-defined]

    await app._run_auto_refresh()
    await entered.wait()

    assert app.refresh_calls == ["agents"]
    assert app._dirty_agents is False

    release.set()
    await asyncio.gather(*tuple(app._pump_free_async_tasks))


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
async def test_new_notification_off_tab_unresolvable_does_not_broad_load() -> None:
    """Unresolvable completions must not trigger an off-tab broad Tier 1 load."""
    app = _FakeApp(watcher_active=True)
    app.current_tab = "patches"
    app._dirty_notifications = True
    app._poll_agent_completions_result = True

    await app._run_auto_refresh()

    assert app.refresh_calls == ["notifications"]
    assert app.refresh_requests == []


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
    assert app.refresh_requests == []
    assert app._dirty_agents is False


@pytest.mark.asyncio
async def test_notification_reconcile_runs_when_unrelated_delta_consumed(
    tmp_path: Path,
) -> None:
    """A tick that consumes an unrelated exact delta still reconciles the notice."""
    app = _FakeApp(watcher_active=True)
    app._dirty_notifications = True
    app._poll_agent_completions_result = True
    unrelated = Path("/tmp/unrelated-agent")
    app._dirty_agent_artifact_dirs = (unrelated,)

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    agent = _make_agent(
        status="DONE",
        cl_name="race-agent",
        raw_suffix="20260722090000",
        artifacts_dir=str(artifacts_dir),
    )
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

    assert "delta:watcher:1" in app.refresh_calls
    assert "delta:notification:1" in app.refresh_calls
    assert "agents" not in app.refresh_calls
    assert app.refresh_requests == []
    assert app.delta_requests == [
        ("watcher", (unrelated,)),
        ("notification", (artifacts_dir,)),
    ]


@pytest.mark.asyncio
async def test_watcher_inactive_runs_full_refresh() -> None:
    """Without a watcher the auto-refresh path keeps polling every surface."""
    app = _FakeApp(watcher_active=False)
    with override_flags(ace_refresh_tokens=False):
        await app._run_auto_refresh()
    assert "axe" in app.refresh_calls
    assert "notifications" in app.refresh_calls
    assert "agents" in app.refresh_calls
    assert app.token_probe_calls == 0


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
