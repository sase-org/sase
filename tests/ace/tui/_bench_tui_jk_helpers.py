"""Shared harness pieces for j/k key-to-paint benchmark modules."""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.patch import Patch
from sase.ace.tui.actions.axe_display._data import (
    AxeCollectedData,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.ace.tui.app import AceApp
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.relations.link_index import LinkChip, LinkIndex
from sase.artifact_ref_entries import reference_for_agent_name
from sase.core.artifact_entry_target import ArtifactEntryTarget

_KEYS_PER_SCENARIO = 20
_AXE_P95_BUDGET_MS = 16.0
# The Patches tab fixture (50 rows) is comparable in scale to the AXE cached
# fixture, so it is held to the same tight epic budget
# (`plans/202608/ace_tui_responsiveness.md`: keystroke-to-paint p95 < 16 ms).
_PATCHES_P95_BUDGET_MS = 16.0
# The 240-agent synthetic list (plus fold groups) is the largest fixture any
# j/k bench here drives, and `J`/`K` panel-group navigation repaints more
# chrome than a plain row move. This ceiling is deliberately generous per
# `plans/202608/ace_tui_responsiveness.md` baseline step 2 -- "where a budget
# cannot be asserted deterministically in CI, assert a generous ceiling
# locally" -- so it catches an order-of-magnitude regression without flaking
# under host contention; the printed table carries the tight number.
_AGENTS_LARGE_LIST_P95_BUDGET_MS = 100.0
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
    app._link_index = LinkIndex(by_ref=by_ref, targets_by_ref={}, source_key=("bench",))
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
def _perf_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    log_path = tmp_path / "tui_jk.jsonl"
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
