"""Node Finder budgets on a synthetic 2,000-node clan tree.

Run explicitly with::

    pytest -s -m slow tests/ace/tui/bench_node_finder.py

Budget table (p95): ``"`` to first paint (snapshot, list, Tier 0) < 50 ms;
keystroke to refiltered list (filter plus the ``OptionList`` update) < 16 ms;
``ctrl+n``/``ctrl+p`` to highlight plus Tier 0 < 16 ms. Tier 1 stays off the
pump behind its 150 ms debounce and is not part of these budgets.
"""

from __future__ import annotations

import statistics
import sys
import time
from datetime import datetime
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._node_finder_snapshot import (
    build_node_finder_snapshot,
)
from sase.ace.tui.modals.node_finder_modal import NodeFinderModal
from sase.ace.tui.modals.node_finder_preview import render_node_finder_preview
from sase.ace.tui.modals.node_finder_preview_loader import NodeFinderPreviewPayload
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.node_finder import filter_node_finder
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
)

pytestmark = pytest.mark.slow

_SAMPLES = 14
_WARMUP_SAMPLES = 3


def _stub_loader(agent: Any) -> NodeFinderPreviewPayload:
    """Keep Tier 1 off disk so the sync budgets measure sync work only."""
    return NodeFinderPreviewPayload(
        identity=agent.identity,
        source_name=agent.agent_name or "stub",
        prompt="stub",
        reply="stub",
        reply_omitted_lines=0,
        reply_omitted_chars=0,
        token=(("stub", 1, 1),),
    )


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, round(percentile * (len(ordered) - 1)))
    return ordered[index]


def _report(name: str, budget_ms: float, samples: list[float]) -> None:
    measured = samples[_WARMUP_SAMPLES:]
    p50 = statistics.median(measured)
    p95 = _percentile(measured, 0.95)
    maximum = max(measured)
    print(
        f"Node Finder {name}: n={len(measured)} budget={budget_ms:.0f}ms "
        f"p50={p50:.2f}ms p95={p95:.2f}ms max={maximum:.2f}ms",
        file=sys.stderr,
    )
    assert p95 < budget_ms, f"{name} p95 {p95:.2f}ms exceeds {budget_ms:.0f}ms"


def _bench_agents(count: int = 2000, clans: int = 10) -> list[Agent]:
    """Synthetic clan/member tree with stable names and timestamps."""
    started = datetime(2026, 7, 17, 9, 0, 0)
    agents: list[Agent] = []
    per_clan = count // clans
    for clan_index in range(clans):
        for member_index in range(per_clan):
            node = member_index + clan_index * per_clan
            agents.append(
                Agent(
                    agent_type=AgentType.RUNNING,
                    cl_name=f"bench-clan-{clan_index}",
                    project_file="/workspace/sase/bench_project.sase",
                    status="RUNNING",
                    start_time=started,
                    raw_suffix=f"20260717090000-bench-{node:04d}",
                    agent_name=f"bench.node.{node:04d}",
                    agent_clan=f"bench-clan-{clan_index}",
                    agent_clan_generation="20260717090000",
                    tribe=None,
                )
            )
    return agents


# One realistic typing burst: early prefixes still match the whole tree while
# the tail narrows to a single node. Intermediate keystrokes coalesce
# latest-wins; only the converged list for the final query is measured.
_BURST = "bench.node.1999"


async def _open_page(monkeypatch: pytest.MonkeyPatch) -> Any:
    patch_startup_loaders(monkeypatch, agents=_bench_agents())
    page = AcePage(query='"bench"', patches=patches(), initial_tab="agents")
    await page.__aenter__()
    await wait_for_startup(page)
    return page


async def test_bench_node_finder_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot plus first filter plus Tier 0 preview stays under 50 ms p95."""
    page = await _open_page(monkeypatch)
    try:
        samples: list[float] = []
        for _ in range(_SAMPLES):
            started = time.perf_counter()
            snapshot = build_node_finder_snapshot(page.app)
            view = filter_node_finder(snapshot, "")
            assert view.best_index is not None
            render_node_finder_preview(view.rows[view.best_index], snapshot, "")
            samples.append((time.perf_counter() - started) * 1000.0)
        _report("open", 50.0, samples)
    finally:
        await page.__aexit__(None, None, None)


async def test_bench_node_finder_keystroke(monkeypatch: pytest.MonkeyPatch) -> None:
    """A typed burst converges to the final query's list under 16 ms p95.

    Keystrokes coalesce latest-wins (the sync callback only arms the next-tick
    worker), so a burst collapses to one rebuild. The measured span runs from
    the burst's last keystroke to the converged list for the full query.
    """
    page = await _open_page(monkeypatch)
    try:
        from textual.widgets import Input

        from sase.ace.tui.modals.base import FilterInput

        snapshot = build_node_finder_snapshot(page.app)
        modal = NodeFinderModal(snapshot, has_back=False, preview_loader=_stub_loader)
        page.app.push_screen(modal)
        await page.expect_modal("NodeFinderModal")
        await page.pause()

        # Part A: the synchronous keystroke callback itself stays thin even
        # when the pending list is huge — scheduling only, never filtering.
        dispatch: list[float] = []
        for sample in range(_SAMPLES):
            started = time.perf_counter()
            modal.on_input_changed(
                Input.Changed(
                    modal.query_one("#node-finder-query", FilterInput),
                    f"bench.node.{sample:04d}",
                )
            )
            dispatch.append((time.perf_counter() - started) * 1000.0)
        _report("keystroke-dispatch", 16.0, dispatch)
        modal._flush_pending_refilter()
        await page.pause()

        samples: list[float] = []
        for _ in range(_SAMPLES):
            await page.press("tab")
            for key in _BURST:
                await page.press(key)
            started = time.perf_counter()
            await page.wait_for(
                lambda _screen: (
                    modal._view.query == _BURST
                    and modal._pending_refilter_query is None
                )
            )
            samples.append((time.perf_counter() - started) * 1000.0)
            assert modal._view.query == _BURST
            assert len(modal._view.rows) >= 1
            query_input = modal.query_one("#node-finder-query", FilterInput)
            query_input.value = ""
            query_input.post_message(Input.Changed(query_input, ""))
            await page.wait_for(
                lambda _screen: (
                    modal._view.query == "" and modal._pending_refilter_query is None
                )
            )
            await page.press("tab")
            await page.pause()
        _report("keystroke", 16.0, samples)
    finally:
        await page.__aexit__(None, None, None)


async def test_bench_node_finder_highlight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cursor step plus Tier 0 repaint stays under 16 ms p95."""
    page = await _open_page(monkeypatch)
    try:
        snapshot = build_node_finder_snapshot(page.app)
        modal = NodeFinderModal(snapshot, has_back=False, preview_loader=_stub_loader)
        page.app.push_screen(modal)
        await page.expect_modal("NodeFinderModal")
        await page.pause()

        samples: list[float] = []
        for sample in range(_SAMPLES):
            direction = 1 if sample % 2 == 0 else -1
            started = time.perf_counter()
            modal._move_cursor(direction)
            modal._paint_preview()
            samples.append((time.perf_counter() - started) * 1000.0)
        _report("highlight", 16.0, samples)
    finally:
        await page.__aexit__(None, None, None)
