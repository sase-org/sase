"""Agents-tab link rail j/k key-to-paint benchmark case."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.app import AceApp
from sase.ace.tui.widgets import LinkRail
from tests.ace.tui._bench_tui_jk_helpers import (
    _LINK_RAIL_AB_ROUNDS,
    _LINK_RAIL_KEYS_PER_ROUND,
    _LINK_RAIL_P95_DELTA_BUDGET_MS,
    _install_agents_fixture,
    _install_link_index_fixture,
    _perf_jsonl as _perf_jsonl,
    _print_table,
    _read_samples,
    _summarize,
    _wait_for_startup,
    _warm_agents_navigation,
)

pytestmark = pytest.mark.slow


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
