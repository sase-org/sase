"""Steady-state harness for j/k key-to-paint latency.

Drives the ace TUI through ``Pilot`` with ``SASE_TUI_PERF=1`` enabled,
captures key-to-paint samples to a JSONL file, and prints a p50/p95/max
table per scenario. Marked ``slow`` so it does not run as part of the
default ``just test`` suite -- run explicitly with::

    pytest -s -m slow tests/ace/tui/bench_tui_jk.py

Each test populates the relevant in-memory model (Patches, Agents)
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

from sase.ace.patch import Patch
from sase.ace.tui.actions.axe_display._data import (
    AxeCollectedData,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.ace.tui.app import AceApp
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.models.fold_scale import CLAN_FOLD_SCALE, TRIBE_FOLD_SCALE
from sase.ace.tui.relations.link_index import LinkChip, LinkIndex
from sase.ace.tui.widgets import LinkRail
from sase.artifact_ref_entries import reference_for_agent_name
from sase.core.artifact_entry_target import ArtifactEntryTarget

pytestmark = pytest.mark.slow

_KEYS_PER_SCENARIO = 20
_AXE_P95_BUDGET_MS = 16.0
# A selected-panel hop repaints two disjoint panel chrome regions (departed
# and destination), unlike a row move's single cursor region. Keep that path
# within two 60 Hz frames while the ordinary row/clan budget remains 16 ms.
_SELECTED_TRIBE_P95_BUDGET_MS = 40.0
_SELECTED_TRIBE_KEYS_PER_SCENARIO = 40
# The rail paints undebounced on the key-to-paint path. Its absolute p95 is
# dominated by the list underneath it, so what is budgeted is how much the
# rail *adds*: still under a third of a 60 Hz frame. Short alternating rounds,
# pooled, keep host-load drift off that delta -- see the test's docstring.
# Sized against 16 measured deltas on a loaded dev host, which spanned
# -2.8 ms to +2.9 ms; the rail's real cost is below that noise floor, so this
# catches a regression rather than resolving the rail itself.
_LINK_RAIL_P95_DELTA_BUDGET_MS = 5.0
# 4 rounds x 12 j + 12 k pools 48 samples per direction per arm. p95 then sits
# 2 samples below the top, so the host's occasional ~250 ms scheduler stall
# lands in `max` without moving either arm's p95.
_LINK_RAIL_AB_ROUNDS = 4
_LINK_RAIL_KEYS_PER_ROUND = 12


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


def _make_patch(name: str, file_path: Path) -> Patch:
    return Patch(
        name=name,
        description=f"synthetic {name}",
        parent=None,
        cl=None,
        status="WIP",
        file_path=str(file_path),
        line_number=1,
    )


def _make_agent(i: int) -> Agent:
    tribes = [None, "alpha", "beta", "gamma"]
    statuses = ["RUNNING", "WAITING", "STARTING", "PLAN", "DONE", "FAILED"]
    project = f"proj{i % 18:02d}"
    tribe = tribes[i % len(tribes)]
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"cl_{i % 40:03d}",
        project_file=f"/tmp/bench/{project}/project.sase",
        status=statuses[i % len(statuses)],
        start_time=None,
        agent_name=f"agent_{i:04d}",
        raw_suffix=f"20260513{i:06d}",
        tribe=tribe,
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


def _install_link_index_fixture(app: AceApp, *, links_per_agent: int = 3) -> None:
    """Give every fixture agent links so the rail repaints on every j/k.

    ``links_per_agent=0`` installs the *same* index shape with no chips, which
    is the honest rail-absent baseline: an index that exists keeps
    ``refresh_link_rail`` from scheduling a real, disk-backed
    ``load_artifact_links_snapshot`` build on the first measured keystroke.
    """

    by_ref: dict[str, tuple[LinkChip, ...]] = {}
    for agent in app._agents:
        name = agent.agent_name
        ref = reference_for_agent_name(name) if name else None
        if ref is None:
            continue
        by_ref[ref] = tuple(
            LinkChip(
                relation="implements",
                label="implements",
                directed=True,
                this_is_source=True,
                neighbor_ref=f"bead:bench-{index:02d}",
                neighbor_target=ArtifactEntryTarget(
                    "beads", ("bench", "task", f"bench-{index:02d}")
                ),
                accent="#00D7AF",
                icon="◈",
                why="bench fixture edge kept off the render path's I/O",
                origin="manual",
                uses=1,
                created_by="bench",
                created_at="2026-08-27T04:00:00Z",
                writable=True,
            )
            for index in range(links_per_agent)
        )
    app._link_index = LinkIndex(by_ref=by_ref, source_key=("bench",))
    app._link_index_loading = False
    app._link_index_pending = False


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


def _make_axe_cached_data(
    *,
    lumberjack_count: int = 12,
    chops_per_lumberjack: int = 6,
) -> AxeCollectedData:
    """Build a cached AXE data set large enough for j/k benchmarks."""
    lumberjack_names = [f"bench.lumberjack.{i:02d}" for i in range(lumberjack_count)]
    lumberjack_chop_names: dict[str, list[str]] = {}
    chop_snapshots: dict[tuple[str, str], ChopSnapshot] = {}
    lumberjack_snapshots: dict[str, LumberjackSnapshot] = {}

    for lumberjack_idx, lumberjack_name in enumerate(lumberjack_names):
        chops: list[ChopSnapshot] = []
        chop_names = [
            f"cached.chop.{lumberjack_idx:02d}.{chop_idx:02d}"
            for chop_idx in range(chops_per_lumberjack)
        ]
        lumberjack_chop_names[lumberjack_name] = chop_names
        for chop_idx, chop_name in enumerate(chop_names):
            snap = ChopSnapshot(
                lumberjack_name=lumberjack_name,
                chop_name=chop_name,
                description=f"cached AXE benchmark row {lumberjack_idx}.{chop_idx}",
                runs=[],
                enabled=(lumberjack_idx + chop_idx) % 7 != 0,
                script=f"sase_chop_cached_{lumberjack_idx:02d}_{chop_idx:02d}",
                resolved_path=f"/workspace/chops/{chop_name}",
            )
            chop_snapshots[(lumberjack_name, chop_name)] = snap
            chops.append(snap)
        lumberjack_snapshots[lumberjack_name] = LumberjackSnapshot(
            name=lumberjack_name,
            status=None,
            metrics=None,
            log_tail="",
            chops=chops,
        )

    return AxeCollectedData(
        axe_running=True,
        axe_status=None,
        axe_metrics=None,
        axe_output="",
        lumberjack_names=lumberjack_names,
        bgcmd_slots=[],
        lumberjack_statuses=dict.fromkeys(lumberjack_names),
        lumberjack_metrics=dict.fromkeys(lumberjack_names),
        lumberjack_log_tails=dict.fromkeys(lumberjack_names, ""),
        bgcmd_details={},
        lumberjack_chop_names=lumberjack_chop_names,
        chop_snapshots=chop_snapshots,
        lumberjack_snapshots=lumberjack_snapshots,
    )


def _install_axe_fixture(app: AceApp) -> None:
    app._apply_axe_status_data(_make_axe_cached_data())
    app._refresh_axe_display()


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


async def _warm_axe_navigation(pilot: object) -> None:
    """Settle AXE layout and debounce state before recording cached j/k p95."""
    for key in ("j", "k") * 4:
        await pilot.press(key)  # type: ignore[attr-defined]
        await pilot.pause(0.01)  # type: ignore[attr-defined]


async def test_bench_patches_jk(_perf_jsonl: Path, tmp_path: Path) -> None:
    """Measure j/k latency on the Patches tab with 50 synthetic Patches."""
    gp_file = tmp_path / "bench" / "bench.sase"
    gp_file.parent.mkdir(parents=True)
    gp_file.write_text("")
    cs_list = [_make_patch(f"cs_{i:03d}", gp_file) for i in range(50)]

    with patch(
        "sase.ace.patch.find_all_patches_cached",
        return_value=cs_list,
    ):
        app = AceApp(
            query='"cs_"',
            auto_start_axe=False,
            initial_tab="patches",
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
    _print_table("Patches tab j/k baseline:", summary)
    assert samples, "perf JSONL captured no samples; instrumentation may be broken"


async def test_bench_axe_jk(_perf_jsonl: Path) -> None:
    """Measure cached j/k latency on the Axe tab with synthetic AXE rows."""
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("tab")  # next_tab: agents -> patches
        await pilot.pause()
        await pilot.press("tab")  # next_tab: patches -> axe
        await pilot.pause()
        _install_axe_fixture(app)
        await pilot.pause(0.2)
        assert len(app._axe_items) > (_KEYS_PER_SCENARIO * 2)
        await _warm_axe_navigation(pilot)
        before = len(_read_samples(_perf_jsonl))
        for _ in range(_KEYS_PER_SCENARIO):
            await pilot.press("j")
            await pilot.pause(0.01)
        for _ in range(_KEYS_PER_SCENARIO):
            await pilot.press("k")
            await pilot.pause(0.01)

    samples = _read_samples(_perf_jsonl)[before:]
    summary = _summarize(samples)
    _print_table("Axe tab cached j/k baseline:", summary)
    assert samples, "perf JSONL captured no AXE samples; instrumentation may be broken"
    assert {str(sample["tab"]) for sample in samples} == {"axe"}
    assert {"next", "prev"} <= set(summary)
    assert all(stats["p95"] < _AXE_P95_BUDGET_MS for stats in summary.values()), (
        f"AXE cached j/k exceeded {_AXE_P95_BUDGET_MS:g} ms p95: {summary}"
    )
    stall_path = _perf_jsonl.with_name("tui_stalls.jsonl")
    assert not stall_path.exists() or not stall_path.read_text().strip()


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


async def _collect_agents_jk(
    pilot: object, _perf_jsonl: Path, *, keys: int
) -> list[dict[str, object]]:
    """Run one warmed j/k stretch and return only its own raw samples."""
    await _warm_agents_navigation(pilot)
    before = len(_read_samples(_perf_jsonl))
    for _ in range(keys):
        await pilot.press("j")  # type: ignore[attr-defined]
        await pilot.pause(0.01)  # type: ignore[attr-defined]
    for _ in range(keys):
        await pilot.press("k")  # type: ignore[attr-defined]
        await pilot.pause(0.01)  # type: ignore[attr-defined]
    return _read_samples(_perf_jsonl)[before:]


async def test_bench_agents_jk_with_and_without_the_link_rail(
    _perf_jsonl: Path,
) -> None:
    """Keep the rail off the felt part of key-to-paint (``bead:sase-ug.6``).

    The rail is deliberately undebounced (``tui_perf`` rule 7), so it repaints
    on every highlight move. The absolute p95 on this scenario is dominated by
    the 240-row Agents list and varies with the host, so what is asserted here
    is the *delta*: the same warmed j/k run, in the same app, with a hidden
    rail and then with an index in which every agent has links -- far denser
    than the real graph, where 81.5% of linked entities have exactly one link
    and most entities have none.

    Two measurement hazards make the naive form of this A/B unusable, and both
    are worth keeping fixed:

    1. *Both* arms must install an index fixture. Leaving ``_link_index`` unset
       for the baseline makes the first measured keystroke schedule a real
       ``load_artifact_links_snapshot`` build against the host's live artifact
       index, charging that disk work -- and the repaint that lands when it
       finishes -- to the baseline. A chipless index hides the rail without
       scheduling anything.
    2. The arms must be *interleaved*, not run once each back to back. This
       host's absolute j/k p50 drifts between 12 ms and 20 ms across runs as
       background load changes, which is larger than the rail's own cost; two
       sequential arms sample that drift at two different times and hand the
       difference to the rail. Alternating short rounds and pooling their
       samples lets the drift land on both arms instead.
    """
    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_agents_fixture(app)
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        await pilot.pause()
        rail = app.query_one("#link-rail", LinkRail)

        async def _arm(*, painting: bool) -> list[dict[str, object]]:
            _install_link_index_fixture(app, links_per_agent=3 if painting else 0)
            app.refresh_link_rail()
            await pilot.pause()
            assert rail.display is painting, (
                f"expected rail.display={painting} for this arm; a chipless "
                "index must hide the rail and a populated one must paint it"
            )
            return await _collect_agents_jk(
                pilot, _perf_jsonl, keys=_LINK_RAIL_KEYS_PER_ROUND
            )

        # Whichever arm goes first absorbs the one-time lazy Textual layout and
        # renderer work that `_warm_agents_navigation`'s 8 keys do not reach --
        # it shows up as a lone ~250 ms sample. Spend a discarded round on it so
        # no measured round is charged for it.
        await _arm(painting=False)

        absent_samples: list[dict[str, object]] = []
        present_samples: list[dict[str, object]] = []
        for _ in range(_LINK_RAIL_AB_ROUNDS):
            absent_samples += await _arm(painting=False)
            present_samples += await _arm(painting=True)

    absent = _summarize(absent_samples)
    present = _summarize(present_samples)
    _print_table("Agents tab j/k, rail absent:", absent)
    _print_table("Agents tab j/k, rail painting:", present)
    assert absent and present, "perf JSONL captured no samples"
    for scenario, stats in present.items():
        baseline = absent.get(scenario)
        assert baseline is not None, f"no rail-absent baseline for {scenario}"
        delta = stats["p95"] - baseline["p95"]
        assert delta < _LINK_RAIL_P95_DELTA_BUDGET_MS, (
            f"the rail added {delta:.2f} ms to {scenario} p95 "
            f"(absent {baseline['p95']:.2f} ms, present {stats['p95']:.2f} ms); "
            f"budget is {_LINK_RAIL_P95_DELTA_BUDGET_MS:g} ms"
        )
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
