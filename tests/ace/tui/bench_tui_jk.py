"""Steady-state harness for j/k key-to-paint latency.

Drives the ace TUI through ``Pilot`` with ``SASE_TUI_PERF=1`` enabled,
captures key-to-paint samples to a JSONL file, and prints a p50/p95/max
table per scenario. Marked ``slow`` so it does not run as part of the
default ``just test`` suite -- run explicitly with::

    pytest -s -m slow tests/ace/tui/bench_tui_jk.py

Each test populates the relevant in-memory model (ChangeSpecs, Agents)
directly so the bench measures *navigation* latency, not disk I/O during
startup. A short unmeasured warmup after fixture/fold changes keeps lazy
Textual layout and renderer initialization out of the steady-state p95.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.app import AceApp
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.models.fold_scale import CLAN_FOLD_SCALE, TRIBE_FOLD_SCALE

pytestmark = pytest.mark.slow

_KEYS_PER_SCENARIO = 20
# A selected-panel hop repaints two disjoint panel chrome regions (departed
# and destination), unlike a row move's single cursor region. Keep that path
# within two 60 Hz frames while the ordinary row/clan budget remains 16 ms.
_SELECTED_TRIBE_P95_BUDGET_MS = 40.0
_SELECTED_TRIBE_KEYS_PER_SCENARIO = 40


async def _wait_for_startup(app: AceApp, pilot: object) -> None:
    """Keep asynchronous startup work out of navigation measurements."""
    deadline = asyncio.get_running_loop().time() + 20.0
    while not (
        app._mount_state_loads_done
        and app._agents_first_load_done
        and app._axe_first_load_done
    ):
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("ACE benchmark startup did not settle within 20s")
        await pilot.pause()  # type: ignore[attr-defined]


def _make_changespec(name: str, file_path: Path) -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description=f"synthetic {name}",
        parent=None,
        cl=None,
        status="WIP",
        file_path=str(file_path),
        line_number=1,
    )


def _make_agent(i: int) -> Agent:
    tags = [None, "alpha", "beta", "gamma"]
    statuses = ["RUNNING", "WAITING", "STARTING", "PLAN", "DONE", "FAILED"]
    project = f"proj{i % 18:02d}"
    tag = tags[i % len(tags)]
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"cl_{i % 40:03d}",
        project_file=f"/tmp/bench/{project}/project.sase",
        status=statuses[i % len(statuses)],
        start_time=None,
        agent_name=f"agent_{i:04d}",
        raw_suffix=f"20260513{i:06d}",
        tribe=tag,
    )


def _install_agents_fixture(app: AceApp, count: int = 240) -> None:
    agents = [_make_agent(i) for i in range(count)]
    registry = AgentGroupFoldRegistry()
    for project_idx in range(0, 18, 5):
        registry.collapse((f"proj{project_idx:02d}",))
    app._agents = agents
    app._agents_with_children = list(agents)
    app._fold_counts = {}
    app._group_fold_registry = registry
    app._panel_group = AgentPanelGroup.from_agents(agents)
    app._agent_panels_grouped = False
    app._current_group_key = None
    app.current_idx = 0
    app._invalidate_agent_panel_cache()


def _make_clan_member(i: int) -> Agent:
    clan = f"bench-clan-{i:03d}"
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{clan}-phase",
        project_file="/tmp/bench/clans/project.sase",
        status="FAILED" if i % 7 == 0 else "RUNNING",
        start_time=datetime(2026, 7, 18, 12, i % 60, 0),
        raw_suffix=f"2026071812{i:04d}-phase",
        agent_name=f"{clan}.phase",
        agent_clan=clan,
        agent_clan_generation=f"20260718{i:06d}",
        clan_tribe="perf",
        error_message="representative failure" if i % 7 == 0 else None,
        output_variables={"summary": f"clan {i} ready"},
        model="gpt-5",
    )


def _install_clan_agents_fixture(app: AceApp, count: int = 48) -> None:
    projected = project_clan_tree([_make_clan_member(i) for i in range(count)])
    visible = [agent for agent in projected if agent.is_clan_container]
    registry = AgentGroupFoldRegistry()
    app._agents = visible
    app._agents_with_children = list(projected)
    app._fold_counts = {}
    app._group_fold_registry = registry
    app._panel_group = AgentPanelGroup.from_agents(visible)
    app._agent_panels_grouped = False
    app._current_group_key = None
    app.current_idx = 0
    app._invalidate_agent_panel_cache()


@pytest.fixture
def _perf_jsonl(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    log_path = Path(str(tmp_path)) / "tui_jk.jsonl"  # type: ignore[arg-type]
    monkeypatch.setenv("SASE_TUI_PERF", "1")
    monkeypatch.setenv("SASE_TUI_PERF_PATH", str(log_path))
    monkeypatch.setenv(
        "SASE_TUI_STALL_PATH",
        str(log_path.with_name("tui_stalls.jsonl")),
    )
    yield log_path


def _read_samples(log_path: Path) -> list[dict[str, object]]:
    if not log_path.exists():
        return []
    return [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]


def _summarize(samples: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    by_action: dict[str, list[float]] = {}
    for s in samples:
        by_action.setdefault(str(s["action"]), []).append(float(s["paint_ms"]))  # type: ignore[arg-type]
    out: dict[str, dict[str, float]] = {}
    for action, vals in by_action.items():
        vs = sorted(vals)
        n = len(vs)
        p95_idx = max(0, int(round(0.95 * (n - 1))))
        out[action] = {
            "n": float(n),
            "p50": float(statistics.median(vs)),
            "p95": vs[p95_idx],
            "max": vs[-1],
        }
    return out


def _print_table(title: str, summary: dict[str, dict[str, float]]) -> None:
    print(f"\n{title}", file=sys.stderr)
    print(
        f"  {'scenario':<24} {'n':>4} {'p50_ms':>8} {'p95_ms':>8} {'max_ms':>8}",
        file=sys.stderr,
    )
    for action, stats in sorted(summary.items()):
        print(
            f"  {action:<24} {int(stats['n']):>4d} "
            f"{stats['p50']:>8.2f} {stats['p95']:>8.2f} {stats['max']:>8.2f}",
            file=sys.stderr,
        )


async def _warm_agents_navigation(pilot: object) -> None:
    """Settle both navigation directions before recording a fold-level p95."""
    for key in ("j", "k") * 4:
        await pilot.press(key)  # type: ignore[attr-defined]
        await pilot.pause(0.01)  # type: ignore[attr-defined]


async def test_bench_changespecs_jk(_perf_jsonl: Path, tmp_path: Path) -> None:
    """Measure j/k latency on the ChangeSpecs tab with 50 synthetic ChangeSpecs."""
    gp_file = tmp_path / "bench" / "bench.sase"
    gp_file.parent.mkdir(parents=True)
    gp_file.write_text("")
    cs_list = [_make_changespec(f"cs_{i:03d}", gp_file) for i in range(50)]

    with patch(
        "sase.ace.changespec.find_all_changespecs_cached",
        return_value=cs_list,
    ):
        app = AceApp(
            query='"cs_"',
            auto_start_axe=False,
            initial_tab="changespecs",
        )
        async with app.run_test() as pilot:
            await _wait_for_startup(app, pilot)
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("j")
                await pilot.pause(0.01)
            for _ in range(_KEYS_PER_SCENARIO):
                await pilot.press("k")
                await pilot.pause(0.01)

    samples = _read_samples(_perf_jsonl)
    summary = _summarize(samples)
    _print_table("ChangeSpecs tab j/k baseline:", summary)
    assert samples, "perf JSONL captured no samples; instrumentation may be broken"


async def test_bench_axe_jk(_perf_jsonl: Path) -> None:
    """Measure j/k latency on the Axe tab with synthetic bgcmd items."""
    app = AceApp(query="!!!", auto_start_axe=False)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")  # next_tab: agents → changespecs
        await pilot.pause()
        await pilot.press("ctrl+l")  # next_tab: changespecs → axe
        await pilot.pause()
        for _ in range(_KEYS_PER_SCENARIO):
            await pilot.press("j")
            await pilot.pause(0.01)

    samples = _read_samples(_perf_jsonl)
    summary = _summarize(samples)
    _print_table("Axe tab j/k baseline:", summary)
    # No assert on samples: the axe tab may have no items in this minimal
    # fixture (j/k is a no-op when the list is empty), but the test still
    # exercises the dispatch path so a regression in the harness shows up.
    _ = samples  # tolerated empty
    if not summary:
        # Empty axe list means j/k early-returns before the watch hook
        # mutates current_idx -- emit a note so the baseline report can
        # explain the gap rather than silently misreporting zero samples.
        print(
            "  (no samples — axe list empty; current_idx never mutated)",
            file=sys.stderr,
        )


async def test_bench_agents_jk_and_panel_navigation(_perf_jsonl: Path) -> None:
    """Measure Agents-tab row and tag-panel navigation on a large synthetic list."""
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


def main() -> int:
    """Standalone entrypoint: run the bench and print a single combined table.

    Equivalent to ``pytest -s -m slow tests/ace/tui/bench_tui_jk.py`` but
    callable as a plain script so phases 2-5 can compare numbers without
    needing pytest plumbing.
    """
    log = Path(
        os.environ.get(
            "SASE_TUI_PERF_PATH", str(Path.home() / ".sase" / "perf" / "tui_jk.jsonl")
        )
    )
    if log.exists():
        summary = _summarize(_read_samples(log))
        _print_table(f"Aggregate samples in {log}:", summary)
        return 0
    print(f"no perf log at {log}; run pytest with -m slow first", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover -- script entry
    raise SystemExit(main())
