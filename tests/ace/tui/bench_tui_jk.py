"""Steady-state harness for j/k key-to-paint latency.

Drives sase's TUI through ``Pilot`` with ``SASE_TUI_PERF=1`` enabled,
captures key-to-paint samples to a JSONL file, and prints a p50/p95/max
table per scenario. Marked ``slow`` so it does not run as part of the
default ``just test`` suite -- run explicitly with::

    pytest -s -m slow tests/ace/tui/bench_tui_jk.py

The collected benchmark cases live in split ``bench_tui_jk_*`` modules. This
module re-exports them so the historical single-file pytest command still
works, and keeps the standalone aggregate-log ``main()`` entrypoint.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.ace.tui._bench_tui_jk_helpers import (
    _perf_jsonl as _perf_jsonl,
    _print_table,
    _read_samples,
    _summarize,
)
from tests.ace.tui.bench_tui_jk_agent_tabs import (
    test_bench_agents_tab_switch_at_500_roots as test_bench_agents_tab_switch_at_500_roots,
)
from tests.ace.tui.bench_tui_jk_agents import (
    test_bench_agents_jk_and_panel_navigation as test_bench_agents_jk_and_panel_navigation,
    test_bench_clan_jk_at_each_panel_fold_level as test_bench_clan_jk_at_each_panel_fold_level,
    test_bench_selected_tribe_jk_at_each_fold_level as test_bench_selected_tribe_jk_at_each_fold_level,
)
from tests.ace.tui.bench_tui_jk_blocks import (
    test_bench_block_cycle_paged as test_bench_block_cycle_paged,
    test_bench_sticky_reply_heavy_sessions as test_bench_sticky_reply_heavy_sessions,
)
from tests.ace.tui.bench_tui_jk_final import (
    test_bench_agents_jk_with_final_pinned as test_bench_agents_jk_with_final_pinned,
)
from tests.ace.tui.bench_tui_jk_fleet import (
    test_bench_agents_fleet_jk_fault_scenarios as test_bench_agents_fleet_jk_fault_scenarios,
)
from tests.ace.tui.bench_tui_jk_keypath import (
    test_bench_keystroke_reaches_no_provider_discovery_or_subprocess as test_bench_keystroke_reaches_no_provider_discovery_or_subprocess,
)
from tests.ace.tui.bench_tui_jk_link_rail import (
    test_bench_agents_jk_with_and_without_the_link_rail as test_bench_agents_jk_with_and_without_the_link_rail,
)
from tests.ace.tui.bench_tui_jk_panes import (
    test_bench_axe_jk as test_bench_axe_jk,
    test_bench_patches_jk as test_bench_patches_jk,
)
from tests.ace.tui.bench_tui_jk_unread import (
    test_bench_unread_bulk_ack_branches as test_bench_unread_bulk_ack_branches,
    test_bench_unread_jump_branches as test_bench_unread_jump_branches,
)

pytestmark = pytest.mark.slow


async def test_bench_deck_jk_two_vs_three_panels(tmp_path) -> None:
    """Agents j/k wall-clock with two vs three deck panels (16 ms budget)."""
    import statistics
    import time

    from textual.app import App, ComposeResult

    from sase.ace.tui.widgets.agent_detail import AgentDetail
    from sase.ace.tui.widgets.decks.model import DeckLayout
    from tests.ace.tui.widgets._agent_display_helpers import make_artifact_agent
    from tests.ace.tui.widgets.decks._deck_spread_test_helpers import pin_paged

    _ROOT = Path(__file__).resolve().parents[3]

    class _BenchDetailApp(App[None]):
        CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

        def compose(self) -> ComposeResult:
            yield AgentDetail(id="agent-detail-panel")

    async def _measure(panels: int, tag: str) -> tuple[float, float]:
        app = _BenchDetailApp()
        pin_paged(app)
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            subdir = tmp_path / tag
            subdir.mkdir(parents=True, exist_ok=True)
            detail.update_display(make_artifact_agent(subdir, status="DONE"))
            await pilot.pause()
            if panels >= 2:
                detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
                await pilot.pause()
            if panels >= 3:
                detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
                await pilot.pause()
            assert len(detail.deck_area.state.grid.panes) == panels
            samples: list[float] = []
            for key in ("j", "k"):
                for _ in range(15):
                    start = time.perf_counter()
                    await pilot.press(key)
                    await pilot.pause()
                    samples.append((time.perf_counter() - start) * 1000.0)
            ordered = sorted(samples)
            p50 = statistics.median(ordered)
            idx = min(len(ordered) - 1, int(0.95 * len(ordered)))
            return p50, ordered[idx]

    p50_two, p95_two = await _measure(2, "two")
    p50_three, p95_three = await _measure(3, "three")
    print(
        f"\ndeck j/k wall-clock ms: 2 panels p50={p50_two:.2f} p95={p95_two:.2f} | "
        f"3 panels p50={p50_three:.2f} p95={p95_three:.2f} (budget 16 ms)"
    )


def main() -> int:
    """Print a single combined table from an existing benchmark JSONL log."""
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
