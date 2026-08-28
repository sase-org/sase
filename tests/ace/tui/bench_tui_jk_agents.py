"""Agents-tab j/k and fold-level key-to-paint benchmark cases."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.app import AceApp
from sase.ace.tui.models.fold_scale import CLAN_FOLD_SCALE, TRIBE_FOLD_SCALE
from sase.ace.tui.models.fold_state import FoldLevel
from tests.ace.tui._bench_tui_jk_helpers import (
    _AGENTS_LARGE_LIST_P95_BUDGET_MS,
    _KEYS_PER_SCENARIO,
    _SELECTED_TRIBE_KEYS_PER_SCENARIO,
    _SELECTED_TRIBE_P95_BUDGET_MS,
    _install_agents_fixture,
    _install_clan_agents_fixture,
    _perf_jsonl as _perf_jsonl,
    _print_table,
    _read_samples,
    _summarize,
    _wait_for_startup,
    _warm_agents_navigation,
)

pytestmark = pytest.mark.slow


async def test_bench_agents_jk_and_panel_navigation(_perf_jsonl: Path) -> None:
    """Measure Agents-tab row and tribe-panel navigation on a large synthetic list."""
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_agents_fixture(app)
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        await pilot.pause()

        for _ in range(_KEYS_PER_SCENARIO):
            await pilot.press("j")
            await pilot.pause(0.01)
        for _ in range(_KEYS_PER_SCENARIO):
            await pilot.press("k")
            await pilot.pause(0.01)
        for _ in range(_KEYS_PER_SCENARIO):
            await pilot.press("J")
            await pilot.pause(0.01)
        for _ in range(_KEYS_PER_SCENARIO):
            await pilot.press("K")
            await pilot.pause(0.01)

    samples = _read_samples(_perf_jsonl)
    summary = _summarize(samples)
    _print_table("Agents tab j/k/J/K synthetic large-list baseline:", summary)
    assert any(s.get("tab") == "agents" for s in samples)
    assert all(
        stats["p95"] < _AGENTS_LARGE_LIST_P95_BUDGET_MS for stats in summary.values()
    ), (
        f"Agents tab j/k/J/K exceeded {_AGENTS_LARGE_LIST_P95_BUDGET_MS:g} ms p95: "
        f"{summary}"
    )


async def test_bench_clan_jk_at_each_panel_fold_level(_perf_jsonl: Path) -> None:
    """Keep clan key-to-paint p95 below budget at levels 1, 2, and 3."""
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    level_summaries: dict[FoldLevel, dict[str, dict[str, float]]] = {}
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_clan_agents_fixture(app)
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        # Let the initial clan aggregation and the Textual layout pass settle;
        # the samples below measure steady-state navigation, not fixture mount.
        await pilot.pause(0.2)
        assert app._agents
        assert all(agent.is_clan_container for agent in app._agents)

        for index, level in enumerate(CLAN_FOLD_SCALE):
            assert app.panel_fold_level is level
            await _warm_agents_navigation(pilot)
            before = len(_read_samples(_perf_jsonl))
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("j")
                await pilot.pause(0.01)
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("k")
                await pilot.pause(0.01)
            samples = _read_samples(_perf_jsonl)[before:]
            summary = _summarize(samples)
            level_summaries[level] = summary
            _print_table(f"Agents clan fold level {index + 1}:", summary)
            assert samples
            assert all(stats["p95"] < 16.0 for stats in summary.values()), (
                f"clan fold level {index + 1} exceeded 16 ms p95: {summary}"
            )
            if level is not FoldLevel.FULLY_EXPANDED:
                await pilot.press("z", "z")
                await pilot.pause(0.2)

    assert set(level_summaries) == set(CLAN_FOLD_SCALE)
    stall_path = _perf_jsonl.with_name("tui_stalls.jsonl")
    assert not stall_path.exists() or not stall_path.read_text().strip()


async def test_bench_selected_tribe_jk_at_each_fold_level(
    _perf_jsonl: Path,
) -> None:
    """Keep selected-tribe panel cycling below budget at all four levels."""
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    level_summaries: dict[FoldLevel, dict[str, dict[str, float]]] = {}
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_agents_fixture(app, count=48)
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        await pilot.pause(0.2)
        assert len(app._panel_group.panel_keys) == 4
        assert app._activate_focused_panel() is True
        assert app._resolve_focused_panel() is not None

        for index, level in enumerate(TRIBE_FOLD_SCALE):
            assert app.panel_fold_level is level
            assert (
                len(app._panel_group.panel_keys),
                app._agent_panels_grouped,
            ) == (4, False)
            assert app._resolve_focused_panel() is not None
            await _warm_agents_navigation(pilot)
            assert (
                len(app._panel_group.panel_keys),
                app._agent_panels_grouped,
            ) == (4, False)
            assert app._resolve_focused_panel() is not None
            before = len(_read_samples(_perf_jsonl))
            # Forty samples per direction keep the p95 meaningful when the
            # host occasionally delays one renderer frame.
            for _ in range(_SELECTED_TRIBE_KEYS_PER_SCENARIO):
                await pilot.press("j")
                await pilot.pause(0.01)
            for _ in range(_SELECTED_TRIBE_KEYS_PER_SCENARIO):
                await pilot.press("k")
                await pilot.pause(0.01)
            samples = _read_samples(_perf_jsonl)[before:]
            summary = _summarize(samples)
            level_summaries[level] = summary
            _print_table(f"Agents selected tribe fold level {index + 1}:", summary)
            assert samples
            assert all(
                stats["p95"] < _SELECTED_TRIBE_P95_BUDGET_MS
                for stats in summary.values()
            ), (
                f"tribe fold level {index + 1} exceeded "
                f"{_SELECTED_TRIBE_P95_BUDGET_MS:g} ms p95: {summary}"
            )
            if level is not FoldLevel.EXHAUSTIVE:
                await pilot.press("z", "z")
                await pilot.pause(0.2)

    assert set(level_summaries) == set(TRIBE_FOLD_SCALE)
    stall_path = _perf_jsonl.with_name("tui_stalls.jsonl")
    assert not stall_path.exists() or not stall_path.read_text().strip()
