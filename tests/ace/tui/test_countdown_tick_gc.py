"""SAVEALL probe of one Agents-tab countdown-tick repaint."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._roster_generation import set_agents_roster
from sase.ace.tui.app import AceApp
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.textual_cycle_guards import install_textual_cycle_guards
from tests.ace.tui._gc_cycles import collect_cyclic_garbage

_AGENT_COUNT = 100
_STRIP = "textual.strip.Strip"
_FIFO = "textual.cache.FIFOCache"
_SASE_PREFIX = "sase."


def _make_agent(index: int) -> Agent:
    tribe = ("alpha", "beta", "gamma")[index % 3]
    status = "DONE" if index % 7 == 0 else "RUNNING"
    run_start = datetime(2026, 9, 1, 12, index % 60, 0) if status == "RUNNING" else None
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"cycle-bench-{index:04d}",
        project_file="/tmp/bench/cycle/project.sase",
        status=status,
        start_time=datetime(2026, 9, 1, 12, index % 60, 0),
        stop_time=datetime(2026, 9, 1, 13, index % 60, 0) if status == "DONE" else None,
        raw_suffix=f"2026090112{index:06d}",
        agent_name=f"cycle-bench-{index:04d}",
        tribe=tribe,
        run_start_time=run_start,
    )
    if index % 3 == 0:
        agent.agent_clan = f"cycle-clan-{index % 30:03d}"
        agent.agent_clan_generation = "20260901000000"
        agent.clan_tribe = tribe
    return agent


def _install_roster(app: AceApp, count: int) -> list[Agent]:
    members = [_make_agent(index) for index in range(count)]
    set_agents_roster(app, agents_with_children=list(members))
    app._agents_local_with_children = list(members)
    app._agents_local_visible = list(members)
    app._fold_counts = {}
    app._agent_panels_grouped = False
    app._current_group_key = None
    app.current_idx = 0
    app._invalidate_agent_panel_cache()
    app._reproject_agents_from_current_mode(source="fleet_refresh", force=True)
    return list(app._agents_with_children)


def _countdown_tick_repaint(app: AceApp) -> None:
    """One countdown-tick cosmetic repaint plus a compositor pass."""
    app._update_agents_info_panel()
    app._patch_agent_runtime_rows()
    if app._agents:
        app._try_patch_agent_row(app._agents[0], refresh_info=False)
    app.screen._compositor_refresh()


def _sase_garbage(counts: Counter[str]) -> dict[str, int]:
    return {
        name: count
        for name, count in counts.items()
        if name.startswith(_SASE_PREFIX) and count
    }


async def test_countdown_tick_repaint_leaves_no_strip_or_fifocache_garbage() -> None:
    install_textual_cycle_guards()
    async with AcePage(
        query="!!!",
        size=(200, 50),
        initial_tab="agents",
    ) as page:
        app = page.app
        projected = _install_roster(app, _AGENT_COUNT)
        assert len(projected) >= _AGENT_COUNT
        await page.pause()
        _countdown_tick_repaint(app)
        await page.pause()

        counts = collect_cyclic_garbage(lambda: _countdown_tick_repaint(app), repeat=3)
        assert counts.get(_STRIP, 0) == 0
        assert counts.get(_FIFO, 0) == 0
        # Remaining SAVEALL hits are CPython cells/functions/lists from
        # Textual callbacks, not sase types or Strip/FIFOCache self-cycles.
        assert _sase_garbage(counts) == {}
