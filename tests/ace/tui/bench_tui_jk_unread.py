"""Unread leader-key (,u / ,j) key-to-paint benchmark cases.

Phase ``unread-instrumentation`` (epic ``sase-1d7``) baseline: drives the
leader unread keys through ``Pilot`` with ``SASE_TUI_PERF=1`` (and
``SASE_TUI_TRACE=1`` for span coverage) on a screenshot-shaped roster
(about 200 agents, clan containers, three tribes) and prints a
p50/p95/max table per branch. Marked ``slow`` like the other j/k benches:

    pytest -s -m slow tests/ace/tui/bench_tui_jk_unread.py

Four branches per key, matching the epic acceptance shape:

- ``visible``: the unread target sits on a visible row.
- ``collapsed_panel``: the target hides inside a collapsed tribe panel.
- ``collapsed_clan``: the target hides inside a collapsed clan fold.
- ``off_tab``: the target lives on another Agents tab.

The committed ceiling is deliberately generous (same precedent as
``_AGENTS_LARGE_LIST_P95_BUDGET_MS``): it catches an order-of-magnitude
regression without flaking under host contention. The printed tables carry
the tight numbers that later phases compare against.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui.app import AceApp
from sase.ace.tui.models._agent_tree import agent_fold_key, project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from tests.ace.tui._bench_tui_jk_helpers import (
    _print_table,
    _read_samples,
    _summarize,
    _wait_for_startup,
)

pytest_plugins = ("tests.ace.tui._bench_tui_jk_helpers",)
pytestmark = pytest.mark.slow

_UNREAD_KEYS_PER_BRANCH = 10
# Generous ceiling: catches an order-of-magnitude regression without
# flaking under host contention; later phases compare printed numbers.
_UNREAD_P95_BUDGET_MS = 1000.0
_TRIBES = ("alpha", "beta", "gamma")


def _make_unread_bench_agent(i: int) -> Agent:
    """Return one roster row: DONE unread-eligible or a live filler row."""
    tribe = _TRIBES[i % len(_TRIBES)]
    status = "DONE" if i % 7 == 0 else ("RUNNING" if i % 2 == 0 else "WAITING")
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"unread-bench-{i:04d}",
        project_file="/tmp/bench/unread/project.sase",
        status=status,
        start_time=datetime(2026, 9, 1, 12, i % 60, 0),
        stop_time=datetime(2026, 9, 1, 13, i % 60, 0) if status == "DONE" else None,
        raw_suffix=f"2026090112{i:06d}",
        agent_name=f"unread-bench-{i:04d}",
        tribe=tribe,
    )
    if i % 3 == 0:
        clan = f"bench-clan-{i % 60:03d}"
        agent.agent_clan = clan
        agent.agent_clan_generation = "20260901000000"
        agent.clan_tribe = tribe
    return agent


def _install_unread_roster(app: AceApp, *, count: int = 200) -> list[Agent]:
    """Install the screenshot-shaped roster; return the DONE targets."""
    members = [_make_unread_bench_agent(i) for i in range(count)]
    projected = project_clan_tree(members)
    app._agents = list(projected)
    app._agents_with_children = list(projected)
    app._fold_counts = {}
    app._panel_group = AgentPanelGroup.from_agents(list(projected))
    app._agent_panels_grouped = False
    app._current_group_key = None
    app.current_idx = 0
    app._invalidate_agent_panel_cache()
    app._refresh_agents_display(list_changed=True, defer_detail=True)
    return [agent for agent in projected if agent.status == "DONE"]


def _arm_unread(app: AceApp, targets: list[Agent]) -> None:
    """Mark *targets* unread without touching the notification store."""
    app._unread_completed_agent_ids = {agent.identity for agent in targets}
    app._manual_unread_agent_ids = set()
    app._pending_bulk_read_agent_ids = None


def _branch_unread_targets(
    app: AceApp, targets: list[Agent], branch: str
) -> list[Agent]:
    """Arrange visibility for *branch*; return the unread targets."""
    if branch == "collapsed_panel":
        panel_key = app._panel_group.panel_keys[0]
        app._collapsed_panel_keys = {panel_key}
        app._panel_group = AgentPanelGroup.from_agents(
            app._agents, collapsed_panel_keys=app._collapsed_panel_keys
        )
        app._refresh_agents_display(list_changed=True, defer_detail=True)
    elif branch == "collapsed_clan":
        containers = [a for a in app._agents_with_children if a.is_clan_container]
        assert containers, "bench roster has no clan containers"
        fold_key = agent_fold_key(containers[0])
        assert isinstance(fold_key, str)
        app._fold_manager.collapse(fold_key)
        app._refilter_agents()
        app._refresh_agents_display(list_changed=True, defer_detail=True)
    elif branch == "off_tab":
        for i, agent in enumerate(app._agents_with_children):
            if i % 2 == 0:
                agent.agent_tab = "sase"
        app._ensure_agent_tabs_state()
        app._refresh_agent_tab_index()
        app._rescope_agents_to_active_tab()
        app._panel_group = AgentPanelGroup.from_agents(app._agents)
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        tab_targets = [
            agent for agent in targets if getattr(agent, "agent_tab", None) == "sase"
        ]
        assert tab_targets, "bench roster has no off-tab DONE targets"
        return tab_targets
    return targets


async def _press_leader(pilot: object, subkey: str) -> None:
    """Press ``,<subkey>`` through the real leader-mode key pipeline."""
    await pilot.press(",")  # type: ignore[attr-defined]
    await pilot.pause(0.01)  # type: ignore[attr-defined]
    await pilot.press(subkey)  # type: ignore[attr-defined]
    await pilot.pause(0.05)  # type: ignore[attr-defined]


async def _measure_branch(
    app: AceApp,
    pilot: object,
    log_path: Path,
    *,
    branch: str,
    subkey: str,
    action: str,
) -> dict[str, dict[str, float]]:
    """Record one branch; return its key-to-paint summary."""
    targets = _install_unread_roster(app)
    branch_targets = _branch_unread_targets(app, targets, branch)
    await pilot.pause(0.1)  # type: ignore[attr-defined]
    # Warm the jump/ack paint path so the samples measure steady state,
    # not first-press detail/debounce cold start (same precedent as
    # _warm_agents_navigation).
    for _ in range(3):
        if subkey == "j":
            _arm_unread(app, branch_targets)
        await _press_leader(pilot, subkey)
    if subkey == "u":
        _arm_unread(app, branch_targets)
    before = len(_read_samples(log_path))
    for _ in range(_UNREAD_KEYS_PER_BRANCH):
        if subkey == "j":
            # Each jump consumes its target; re-arm for steady-state cost.
            _arm_unread(app, branch_targets)
        await _press_leader(pilot, subkey)
    samples = _read_samples(log_path)[before:]
    summary = _summarize(samples)
    _print_table(f"Unread ,{subkey} branch {branch!r}:", summary)
    assert action in summary, f"no {action!r} samples in branch {branch!r}: {summary}"
    stats = summary[action]
    assert stats["p95"] < _UNREAD_P95_BUDGET_MS, (
        f",{subkey} branch {branch!r} exceeded "
        f"{_UNREAD_P95_BUDGET_MS:g} ms p95: {stats}"
    )
    return summary


async def _run_unread_branches(
    log_path: Path, monkeypatch: pytest.MonkeyPatch, *, subkey: str, action: str
) -> dict[str, dict[str, dict[str, float]]]:
    """Drive *subkey* across all four branches on a fresh app."""
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv(
        "SASE_TUI_TRACE_PATH", str(log_path.with_name("tui_trace_unread.jsonl"))
    )
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        lambda _keys: 0,
    )
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    results: dict[str, dict[str, dict[str, float]]] = {}
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        for branch in ("visible", "collapsed_panel", "collapsed_clan", "off_tab"):
            results[branch] = await _measure_branch(
                app, pilot, log_path, branch=branch, subkey=subkey, action=action
            )
    return results


async def test_bench_unread_bulk_ack_branches(
    _perf_jsonl: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep ,u key-to-paint under budget on every unread branch."""
    results = await _run_unread_branches(
        _perf_jsonl, monkeypatch, subkey="u", action=",u"
    )
    assert set(results) == {"visible", "collapsed_panel", "collapsed_clan", "off_tab"}


async def test_bench_unread_jump_branches(
    _perf_jsonl: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep ,j key-to-paint under budget on every unread branch."""
    results = await _run_unread_branches(
        _perf_jsonl, monkeypatch, subkey="j", action=",j"
    )
    assert set(results) == {"visible", "collapsed_panel", "collapsed_clan", "off_tab"}
