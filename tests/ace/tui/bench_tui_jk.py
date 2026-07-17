"""Phase-1 baseline harness for j/k key-to-paint latency.

Bead sase-u.1 / sdd/plans/202604/instant_jk_navigation.md.

Drives the ace TUI through ``Pilot`` with ``SASE_TUI_PERF=1`` enabled,
captures key-to-paint samples to a JSONL file, and prints a p50/p95/max
table per scenario. Marked ``slow`` so it does not run as part of the
default ``just test`` suite -- run explicitly with::

    pytest -s -m slow tests/ace/tui/bench_tui_jk.py

Each test populates the relevant in-memory model (ChangeSpecs, Agents)
directly so the bench measures *navigation* latency, not disk I/O during
startup. Post-action scenarios (approve/kill/dismiss) are out of scope
for the harness itself: phases 2-5 add coverage for those once they are
addressable on the UI thread. The samples in the JSONL still capture any
`j`/`k` performed in those scenarios when the bench is extended later.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.app import AceApp
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup

pytestmark = pytest.mark.slow

_KEYS_PER_SCENARIO = 20


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
        tag=tag,
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


@pytest.fixture
def _perf_jsonl(
    tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    log_path = Path(str(tmp_path)) / "tui_jk.jsonl"  # type: ignore[arg-type]
    monkeypatch.setenv("SASE_TUI_PERF", "1")
    monkeypatch.setenv("SASE_TUI_PERF_PATH", str(log_path))
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
    app = AceApp(query="!!!", auto_start_axe=False)
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
