"""Agents-tab switch key-to-paint benchmark case (epic sase-1bc finish).

Drives ``]``/``[`` tab cycling on a 500-root two-tab roster and measures
against the contract targets: tab-switch key-to-paint p95 under 50 ms, and
``j``/``k`` p95 under 16 ms on every tab.

The committed ceilings below are deliberately generous per the
``_AGENTS_LARGE_LIST_P95_BUDGET_MS`` precedent: they catch an
order-of-magnitude regression without flaking under host contention (the
sandbox measures switch key-to-paint p50 ~200 ms through the headless
renderer). The printed tables carry the tight numbers for dev-host runs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sase.ace.tui.app import AceApp
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from tests.ace.tui._bench_tui_jk_helpers import (
    _KEYS_PER_SCENARIO,
    _make_agent,
    _print_table,
    _read_samples,
    _summarize,
    _wait_for_startup,
)

pytest_plugins = ("tests.ace.tui._bench_tui_jk_helpers",)
pytestmark = pytest.mark.slow

# Contract targets (dev host): switch p95 < 50 ms, j/k p95 < 16 ms.
_TAB_SWITCH_P95_BUDGET_MS = 1000.0
_TAB_JK_P95_BUDGET_MS = 500.0
_TAB_SWITCH_ACTION = "agents_tab_switch"


def _install_tabbed_agents_fixture(app: AceApp, count: int = 500) -> None:
    """Install *count* roots split across the default tab and ``sase``."""
    agents = [_make_agent(i) for i in range(count)]
    for i, agent in enumerate(agents):
        if i % 2 == 0:
            agent.agent_tab = "sase"
    app._agents_with_children = list(agents)
    app._agents_query_result = list(agents)
    app._ensure_agent_tabs_state()
    app._refresh_agent_tab_index()
    app._rescope_agents_to_active_tab()
    app._panel_group = AgentPanelGroup.from_agents(app._agents)
    app._agent_panels_grouped = False
    app._current_group_key = None
    app.current_idx = 0
    app._invalidate_agent_panel_cache()


async def _press_and_await_tab(pilot: object, app: AceApp, key: str) -> None:
    """Press a tab-cycle key and wait until the active tab actually changes."""
    before = app._active_agent_tab
    await pilot.press(key)  # type: ignore[attr-defined]
    deadline = asyncio.get_running_loop().time() + 10.0
    while app._active_agent_tab == before:
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"tab switch on {key!r} did not land within 10s")
        await pilot.pause()  # type: ignore[attr-defined]
    # Let the repaint's mark_painted close the in-flight perf sample before
    # the next press: the recorder holds a single sample at a time.
    await pilot.pause(0.1)  # type: ignore[attr-defined]


async def test_bench_agents_tab_switch_at_500_roots(
    _perf_jsonl: Path,
) -> None:
    """Keep tab-switch key-to-paint p95 under budget at 500 roots."""
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_tabbed_agents_fixture(app)
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        await pilot.pause(0.2)
        assert app._agent_tab_strip_visible()
        keys = [entry.key for entry in app._agent_tab_catalog_view()]
        assert len(keys) == 2

        # Settle the switch path before recording.
        for _ in range(4):
            await _press_and_await_tab(pilot, app, "]")
            await _press_and_await_tab(pilot, app, "[")
        before = len(_read_samples(_perf_jsonl))
        for _ in range(_KEYS_PER_SCENARIO):
            await _press_and_await_tab(pilot, app, "]")
            await _press_and_await_tab(pilot, app, "[")
        samples = _read_samples(_perf_jsonl)[before:]
        summary = _summarize(samples)
        _print_table("Agents tab ]/[ switch at 500 roots:", summary)
        assert _TAB_SWITCH_ACTION in summary, (
            f"no {_TAB_SWITCH_ACTION!r} samples recorded: {summary}"
        )
        switch = summary[_TAB_SWITCH_ACTION]
        assert switch["p95"] < _TAB_SWITCH_P95_BUDGET_MS, (
            f"tab switch exceeded {_TAB_SWITCH_P95_BUDGET_MS:g} ms p95: {switch}"
        )

        # j/k stays under budget on each tab, switching by key so the
        # measurement never depends on cycle order.
        for key in keys:
            app._switch_agents_tab(key, reason="bench")
            await pilot.pause(0.2)
            assert app._active_agent_tab == key
            before = len(_read_samples(_perf_jsonl))
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("j")
                await pilot.pause(0.05)
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("k")
                await pilot.pause(0.05)
            samples = _read_samples(_perf_jsonl)[before:]
            summary = _summarize(samples)
            _print_table(f"Agents tab j/k on {key!r}:", summary)
            assert samples
            assert all(
                stats["p95"] < _TAB_JK_P95_BUDGET_MS for stats in summary.values()
            ), f"j/k exceeded {_TAB_JK_P95_BUDGET_MS:g} ms p95: {summary}"
