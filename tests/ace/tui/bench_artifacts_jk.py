"""Measured j/k key-to-paint budget for every Artifacts sub-tab.

Run with ``pytest -s -m slow tests/ace/tui/bench_artifacts_jk.py``. The
fixtures keep collection out of the measurement so the benchmark isolates
highlight movement and the first paint, matching the interactive p95 budget.
"""

from __future__ import annotations

import json
from pathlib import Path
import statistics

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import ArtifactsBugsPane
from sase.ace.tui.widgets.artifacts import CommitsPane
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
import sase.ace.tui.widgets.artifacts.commits as commits_module
from tests.ace.tui.test_artifacts_bugs import _issue as _bug_issue
from tests.ace.tui.test_artifacts_bugs import _snapshot as _bug_snapshot
from tests.ace.tui.test_artifacts_plans import _choices as _plan_choices
from tests.ace.tui.test_artifacts_plans import _snapshot as _plans_snapshot
from tests.ace.tui.test_commits_pane import _DIFF, _result as _commits_result
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
)

pytestmark = pytest.mark.slow

_KEYS_PER_DIRECTION = 20
_P95_BUDGET_MS = 16.0


async def _press_burst(page: AcePage, key: str) -> None:
    for _ in range(_KEYS_PER_DIRECTION):
        await page.press(key)
        await page.pause()


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

    commits = _commits_result()
    bugs = _bug_snapshot((_bug_issue(41), _bug_issue(42)))
    plans = _plans_snapshot(tmp_path)
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
        "sase.ace.tui.widgets.artifacts.bugs.collect_bug_snapshot",
        lambda *_args, **_kwargs: bugs,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: plans,
    )

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)

        await _press_burst(page, "j")
        await _press_burst(page, "k")

        await page.press("]")
        await page.expect_state("artifacts_subtab", "commits")
        commits_pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: commits_pane.result is commits)
        await _press_burst(page, "j")
        await _press_burst(page, "k")

        page.app.current_artifacts_subtab = "bugs"
        await page.expect_state("artifacts_subtab", "bugs")
        bugs_pane = page.query_one_widget("#artifacts-bugs-pane", ArtifactsBugsPane)
        await page.wait_for(lambda _state: len(bugs_pane.issues) == 2)
        await _press_burst(page, "j")
        await _press_burst(page, "k")

        page.app.current_artifacts_subtab = "plans"
        await page.expect_state("artifacts_subtab", "plans")
        plans_pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: plans_pane.snapshot is plans)
        await _press_burst(page, "j")
        await _press_burst(page, "k")

    samples = _read_samples(perf_path)
    expected_actions = (
        "next",
        "prev",
        "commits.next",
        "commits.prev",
        "bugs.next",
        "bugs.prev",
        "plans.next",
        "plans.prev",
    )
    print("\nArtifacts j/k key-to-paint")
    print(f"  {'action':<18} {'n':>4} {'p50_ms':>8} {'p95_ms':>8}")
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
        assert p95_ms < _P95_BUDGET_MS
