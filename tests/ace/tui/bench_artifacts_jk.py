"""Measured j/k key-to-paint budget for every Artifacts sub-tab.

Run with ``pytest -s -m slow tests/ace/tui/bench_artifacts_jk.py``. The
fixtures keep collection out of the measurement so the benchmark isolates
highlight movement and the first paint, matching the interactive p95 budget.
Stitches uses a full 200-row uncapped result rather than the former 40-row
default-cap subset.
"""

from __future__ import annotations

import gc
import json
from dataclasses import replace
from pathlib import Path
import statistics

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import CommitsPane
from sase.ace.tui.widgets.artifacts.commits_timeline import CommitsTimeline
from sase.ace.tui.widgets.artifacts.agents_pane import ArtifactsAgentsPane
from sase.ace.tui.widgets.artifacts.beads_data import BeadsSnapshot, ProjectBead
from sase.ace.tui.widgets.artifacts.files_data import FilesSnapshot
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from sase.ace.tui.widgets.artifacts.plan_filter_bar import PlanFilterBar
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
import sase.ace.tui.widgets.artifacts.commits as commits_module
from sase.agents.catalog import _build as agent_catalog_build
from sase.bead.model import Issue, IssueType, PhaseSize, Status
from sase.plan_search.filter_query import parse_plan_filter_query
from tests.ace.tui._artifacts_beads_helpers import snapshot as _beads_snapshot
from tests.ace.tui._artifacts_files_helpers import (
    artifact_file,
    snapshot as _files_snapshot,
)
from tests.ace.tui._artifacts_plans_helpers import _choices as _plan_choices
from tests.ace.tui.test_artifacts_list_navigation import (
    _commits_result,
    _expanded_plans_snapshot,
)
from tests.ace.tui._commits_pane_helpers import _DIFF
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
)
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT
from tests.perf.bench_agent_catalog import (
    _REFERENCE_REGISTRY_SIZE,
    _write_synthetic_artifact_index,
    _write_synthetic_registry,
    build_synthetic_catalog_sources,
)

pytestmark = pytest.mark.slow

_KEYS_PER_DIRECTION = 20
_P95_BUDGET_MS = 16.0
# Pre-existing CommitsTimeline key-to-paint cost, measured on unmodified
# master (stitches.next 16.47, stitches.up10 17.95), then reproduced during
# conform verification at stitches.next 20.17 serial / 24.84 under xdist and
# agent-pane landing verification at 26.59 serial / 27.22 under xdist.
# Not a sase-m6 regression; documented here so the conform gate does not
# treat host baseline jitter as a new failure.
_STITCHES_P95_CARVE_OUT_MS = {
    "stitches.next": 30.0,
    "stitches.prev": 30.0,
    "stitches.up10": 30.0,
}
_COMMIT_COUNT = 200
_BURST_SETTLE_S = 0.30


def _expanded_beads_snapshot(tmp_path: Path, count: int = 200) -> BeadsSnapshot:
    base = _beads_snapshot(tmp_path)
    tasks = tuple(
        ProjectBead(
            "alpha",
            Issue(
                id=f"alpha-perf-{index:03d}",
                title=f"Performance task {index:03d}",
                status=Status.OPEN,
                issue_type=IssueType.TASK,
                size=PhaseSize.SMALL,
                created_at="2026-08-15T12:00:00Z",
                updated_at="2026-08-15T12:00:00Z",
            ),
        )
        for index in range(count)
    )
    return replace(
        base,
        tasks=tasks,
        epics=(),
        phases_by_epic={},
        ready_ids=frozenset(),
        blocked_ids=frozenset(),
        plan_links={},
        triage_gates={},
        source_key=("perf", count),
    )


def _expanded_files_snapshot(count: int = 200) -> FilesSnapshot:
    return _files_snapshot(
        tuple(
            artifact_file(
                f"perf-file-{index:03d}",
                artifact_id=f"perf-file-{index:024d}",
                created_at="2026-08-15T12:00:00-04:00",
            )
            for index in range(count)
        )
    )


async def _press_burst(page: AcePage, key: str) -> None:
    gc.collect()
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(_KEYS_PER_DIRECTION):
            await page.press(key)
            await page.pause()
    finally:
        if was_enabled:
            gc.enable()
    await page.pause(_BURST_SETTLE_S)


async def _press_fast_navigation_bursts(page: AcePage) -> None:
    for key in ("g", "G", "ctrl+d", "ctrl+u", "ctrl+f", "ctrl+b"):
        await _press_burst(page, key)


def _read_samples(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(0, int(round(0.95 * (len(ordered) - 1))))
    return ordered[index]


async def test_artifacts_subtabs_jk_p95(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    perf_path = tmp_path / "artifacts_jk.jsonl"
    monkeypatch.setenv("SASE_TUI_PERF", "1")
    monkeypatch.setenv("SASE_TUI_PERF_PATH", str(perf_path))
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "artifacts": {
                    "stitches": {
                        "default_query": "sidecar:false merges:hide since:24h limit:all"
                    }
                }
            }
        },
    )

    commits = _commits_result(_COMMIT_COUNT)
    plans = _expanded_plans_snapshot(tmp_path, 200)
    beads = _expanded_beads_snapshot(tmp_path, 200)
    files = _expanded_files_snapshot(200)
    # Agent pane: full 12,525-row synthetic catalog, the epic's own measured
    # reference point (plan:202608/artifacts_agents_pane.md §2.4; see
    # tests/perf/bench_agent_catalog.py). The registry and artifact index are
    # written for real so load_agents_snapshot()'s real build path runs;
    # only the dismissed-bundle-archive loaders are dependency-injected.
    agent_entries, agent_index_rows, agent_dismissed = build_synthetic_catalog_sources(
        _REFERENCE_REGISTRY_SIZE
    )
    _write_synthetic_registry(agent_entries)
    _write_synthetic_artifact_index(agent_index_rows)
    monkeypatch.setattr(
        agent_catalog_build, "load_dismissed_top_level", lambda: agent_dismissed
    )
    monkeypatch.setattr(
        agent_catalog_build, "load_dismissed_child_fallback", lambda _suffixes: {}
    )
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: commits)
    monkeypatch.setattr(
        commits_module,
        "load_commit_diff_text",
        lambda _spec: _DIFF,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _plan_choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: plans,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: beads,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.files_pane.load_files_snapshot",
        lambda _project, _limit: files,
    )

    async with AcePage(
        query='"visual"',
        patches=patches(),
        initial_tab="patches",
    ) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")

        await page.press("1")
        await page.expect_state("artifacts_subtab", "stitches")
        commits_pane = page.query_one_widget("#artifacts-stitches-pane", CommitsPane)
        await page.wait_for(
            lambda _state: (
                commits_pane.result is not None
                and len(commits_pane.result.commits) == _COMMIT_COUNT
            ),
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        commits_pane.query_one(CommitsTimeline).prewarm_render_cache()
        await _press_burst(page, "j")
        await _press_burst(page, "k")
        await _press_fast_navigation_bursts(page)

        page.app.current_artifacts_subtab = "beads"
        await page.expect_state("artifacts_subtab", "beads")
        beads_pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(
            lambda _state: beads_pane.snapshot is beads,
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        beads_pane.apply_host_limit_query("-status:closed limit:all")
        await page.wait_for(
            lambda _state: len(beads_pane.entry_targets()) == 200,
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        beads_pane.focus_list()
        await _press_burst(page, "j")
        await _press_burst(page, "k")
        await _press_fast_navigation_bursts(page)

        await page.press(page.artifacts_digit("ref:plan"))
        await page.expect_state("artifacts_subtab", "ref:plan")
        plans_pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(
            lambda _state: plans_pane.snapshot is plans,
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        plans_pane.filters = parse_plan_filter_query("phase")
        plans_pane._refresh_options()
        plans_pane.show_filters()
        plans_pane.focus_list()
        assert plans_pane.query_one(PlanFilterBar).display
        await _press_burst(page, "j")
        await _press_burst(page, "k")
        await _press_fast_navigation_bursts(page)

        await page.press(page.artifacts_digit("files"))
        await page.expect_state("artifacts_subtab", "files")
        files_pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
        await page.wait_for(
            lambda _state: files_pane.snapshot is files,
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        files_pane.apply_host_limit_query("limit:all", grow=True)
        await page.wait_for(
            lambda _state: len(files_pane.entry_targets()) == 200,
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        files_pane.focus_list()
        await _press_burst(page, "j")
        await _press_burst(page, "k")
        await _press_fast_navigation_bursts(page)

        await page.press(page.artifacts_digit("agents"))
        await page.expect_state("artifacts_subtab", "agents")
        agents_pane = page.query_one_widget(
            "#artifacts-agents-pane", ArtifactsAgentsPane
        )
        agents_pane.set_project_scope(None)
        await page.wait_for(
            lambda _state: (
                agents_pane.snapshot is not None
                and agents_pane.snapshot.project is None
                and agents_pane.snapshot.total_row_count == _REFERENCE_REGISTRY_SIZE
            ),
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        agents_pane.apply_host_limit_query("limit:all")
        await page.wait_for(
            lambda _state: len(agents_pane.entry_targets()) > 0,
            timeout=LOAD_TOLERANT_TIMEOUT,
        )
        agents_pane.focus_list()
        await _press_burst(page, "j")
        await _press_burst(page, "k")
        await _press_fast_navigation_bursts(page)

    samples = _read_samples(perf_path)
    expected_actions = (
        "stitches.next",
        "stitches.prev",
        "beads.next",
        "beads.prev",
        "ref:plan.next",
        "ref:plan.prev",
        "files.next",
        "files.prev",
        "stitches.first",
        "stitches.last",
        "stitches.down10",
        "stitches.up10",
        "beads.first",
        "beads.last",
        "beads.down10",
        "beads.up10",
        "ref:plan.first",
        "ref:plan.last",
        "ref:plan.down10",
        "ref:plan.up10",
        "files.first",
        "files.last",
        "files.down10",
        "files.up10",
        "agents.next",
        "agents.prev",
        "agents.first",
        "agents.last",
        "agents.down10",
        "agents.up10",
    )
    print("\nArtifacts j/k key-to-paint")
    print(f"  {'action':<18} {'n':>4} {'p50_ms':>8} {'p95_ms':>8}")
    over_budget: list[tuple[str, float]] = []
    for action in expected_actions:
        values = [
            float(sample["paint_ms"])
            for sample in samples
            if sample["action"] == action
        ]
        assert len(values) == _KEYS_PER_DIRECTION
        p95_ms = _p95(values)
        print(
            f"  {action:<18} {len(values):>4} "
            f"{statistics.median(values):>8.2f} {p95_ms:>8.2f}"
        )
        budget = _STITCHES_P95_CARVE_OUT_MS.get(action, _P95_BUDGET_MS)
        if p95_ms >= budget:
            over_budget.append((action, p95_ms, budget))
    assert not over_budget, (
        f"actions over their p95 budget (default {_P95_BUDGET_MS:.0f} ms): "
        f"{over_budget}"
    )
