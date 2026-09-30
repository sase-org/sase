"""Idle 1 Hz tick and fleet-refresh baseline (unread-instrumentation).

Times one countdown tick (``_patch_agent_runtime_rows``) and one
``fleet_refresh`` reprojection (``_reproject_agents_from_current_mode``) on
the UI thread at the screenshot roster size (about 200 agents, clan
containers, three tribes). The j/k benches cannot see these costs by
design: the tick and fleet apply are skipped while navigating, so this
scenario calls both methods directly on a settled app instead.

Both forced (full projection) and unchanged (signature skip-path)
``fleet_refresh`` variants are timed: the later ``fleet-signature-cheap``
phase compares against the forced number, ``runtime-tick-caches`` against
the tick number.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from sase.ace.tui.app import AceApp
from sase.ace.tui.models.agent import Agent, AgentType

from .common import _summarize_values, _wait_for_startup

_IDLE_REPEATS = 20
_AGENT_COUNT = 200
_TRIBES = ("alpha", "beta", "gamma")


def _make_idle_agent(i: int) -> Agent:
    """Return one idle-scenario row with a ticking runtime suffix."""
    tribe = _TRIBES[i % len(_TRIBES)]
    status = "DONE" if i % 7 == 0 else "RUNNING"
    run_start = datetime(2026, 9, 1, 12, i % 60, 0) if status == "RUNNING" else None
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"idle-bench-{i:04d}",
        project_file="/tmp/bench/idle/project.sase",
        status=status,
        start_time=datetime(2026, 9, 1, 12, i % 60, 0),
        stop_time=datetime(2026, 9, 1, 13, i % 60, 0) if status == "DONE" else None,
        raw_suffix=f"2026090112{i:06d}",
        agent_name=f"idle-bench-{i:04d}",
        tribe=tribe,
        run_start_time=run_start,
    )
    if i % 3 == 0:
        clan = f"idle-clan-{i % 60:03d}"
        agent.agent_clan = clan
        agent.agent_clan_generation = "20260901000000"
        agent.clan_tribe = tribe
    return agent


def _install_idle_roster(app: AceApp, agent_count: int) -> list[Agent]:
    """Install the idle roster through the canonical projection pipeline.

    Raw members go into the same caches the loader fills and the fleet
    reprojection derives the visible roster from them, so later timed
    reprojections preserve rows exactly as production does. Clan members
    stay folded under the default fold state, matching a real session.
    """
    members = [_make_idle_agent(i) for i in range(agent_count)]
    app._agents_with_children = list(members)
    app._agents_local_with_children = list(members)
    app._agents_local_visible = list(members)
    app._fold_counts = {}
    app._agent_panels_grouped = False
    app._current_group_key = None
    app.current_idx = 0
    app._invalidate_agent_panel_cache()
    app._reproject_agents_from_current_mode(source="fleet_refresh", force=True)
    return list(app._agents_with_children)


async def _run_idle_scenario(
    *,
    agent_count: int = _AGENT_COUNT,
    repeats: int = _IDLE_REPEATS,
) -> dict[str, Any]:
    """Run one settled app and time its tick plus fleet reprojection."""
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()

        projected = _install_idle_roster(app, agent_count)
        await pilot.pause(0.2)
        clan_containers = sum(1 for a in projected if a.is_clan_container)
        try:
            from sase.ace.tui.models.agent_time import row_runtime_or_wait_ticks
        except Exception:  # noqa: BLE001 - bench-only predicate count.
            row_runtime_or_wait_ticks = None  # type: ignore[assignment]
        ticking_rows = 0
        if row_runtime_or_wait_ticks is not None:
            try:
                ticking_rows = sum(
                    1 for row in app._agents if row_runtime_or_wait_ticks(row)
                )
            except Exception:  # noqa: BLE001 - bench-only count.
                ticking_rows = 0

        # Settle the Textual layout pass, then time the tick on the full
        # roster before any reprojection touches it.
        app._patch_agent_runtime_rows()
        tick_samples: list[float] = []
        tick_patched: list[int] = []
        for _ in range(repeats):
            started = time.perf_counter()
            tick_patched.append(app._patch_agent_runtime_rows())
            tick_samples.append((time.perf_counter() - started) * 1000.0)

        # Fresh roster so the fleet numbers measure a full roster too; one
        # forced pass settles the applied signature for the unchanged path.
        # ``_agents`` is the visible roster (folded clan members hidden),
        # ``projected`` the loaded one: reprojections must keep the visible
        # roster stable, not expand it to the loaded size.
        projected = _install_idle_roster(app, agent_count)
        await pilot.pause(0.2)
        visible_rows = len(app._agents)
        app._reproject_agents_from_current_mode(source="fleet_refresh", force=True)
        await pilot.pause(0.1)
        assert len(app._agents) == visible_rows, (
            f"fleet reprojection changed the visible roster: {len(app._agents)} "
            f"of {visible_rows} (loaded {len(projected)})"
        )

        unchanged_samples: list[float] = []
        for _ in range(repeats):
            started = time.perf_counter()
            app._reproject_agents_from_current_mode(source="fleet_refresh")
            unchanged_samples.append((time.perf_counter() - started) * 1000.0)
        forced_samples: list[float] = []
        for _ in range(repeats):
            started = time.perf_counter()
            app._reproject_agents_from_current_mode(source="fleet_refresh", force=True)
            forced_samples.append((time.perf_counter() - started) * 1000.0)
        return {
            "agent_count": agent_count,
            "rows": len(projected),
            "visible_rows": visible_rows,
            "clan_containers": clan_containers,
            "tick_ticking_rows": ticking_rows,
            "tick_patched_rows": min(tick_patched),
            "tick_patched_max": max(tick_patched),
            "tick_ms": _summarize_values(tick_samples),
            "fleet_refresh_unchanged_ms": _summarize_values(unchanged_samples),
            "fleet_refresh_forced_ms": _summarize_values(forced_samples),
        }
