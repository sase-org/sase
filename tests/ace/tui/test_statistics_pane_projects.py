"""Projects-report integration coverage for the Statistics pane."""

from __future__ import annotations

import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest
from textual.worker import WorkerState

from sase.ace.testing import AcePage
from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals.statistics_pane import (
    StatisticsPane,
    _StatisticsLoadResult,
    _load_project_code_stats,
)
from sase.ace.tui.modals.statistics_pane_project_merge import merge_project_code_stats
from sase.stats.loader import StatisticsViewData
from sase.stats.registry import PROJECTS_GROUP_ORDER
from sase.stats.render.compose import render_project_stats
from sase.stats.render.context import RenderContext

from tests.ace.tui._statistics_pane_helpers import (
    _open_statistics,
    _patch_center,
    _render_plain,
    _result,
    _wait_statistics_settled,
)
from tests.stats._project_render_fixtures import (
    MACHINE,
    NOW,
    TZ,
    all_projects_view,
    one_project_view,
)


def test_one_project_scope_defaults_to_model_and_skips_project_when_cycling() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "projects"
    pane._project_filter = "sase"
    pane._last_result = _result("projects", pane._range, project_filter="sase")
    pane._projects_group_by = "project"

    assert pane._effective_projects_group_by() == "model"
    assert pane._projects_group_cycle_order() == ("repo", "model", "patch")

    pane.action_cycle_group()
    assert pane._projects_group_by == "patch"
    pane.action_cycle_group()
    assert pane._projects_group_by == "repo"
    pane.action_cycle_group()
    assert pane._projects_group_by == "model"


def test_several_projects_cycle_every_grouping_without_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "projects"
    pane._last_result = _result("projects", pane._range)
    scheduled: list[bool] = []
    monkeypatch.setattr(pane, "_schedule_load", lambda: scheduled.append(True))
    monkeypatch.setattr(pane, "_paint_current_view", lambda: None)

    seen: list[str] = []
    for _ in PROJECTS_GROUP_ORDER:
        pane.action_cycle_group()
        seen.append(pane._projects_group_by)

    assert seen == ["repo", "model", "patch", "project"]
    assert scheduled == []


def test_zero_run_project_is_not_an_empty_state() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "projects"
    report = all_projects_view()
    project = report.projects[0]
    assert project.runs is not None
    zeroed = replace(
        report,
        projects=(
            replace(
                project,
                runs=replace(project.runs, runs=0, completed=0, failed=0),
            ),
        ),
    )
    result = StatisticsViewData(
        view="projects",
        selected_range=pane._range,
        generated_at=NOW.timestamp(),
        project_stats=zeroed,
    )
    pane._last_result = result

    assert pane._current_view_is_empty(result) is False


def test_merge_keeps_output_and_matches_projects_by_key() -> None:
    primary = all_projects_view(facets={"output", "runs"})
    code = all_projects_view(facets={"code"})
    reordered = replace(code, projects=tuple(reversed(code.projects)))

    merged = merge_project_code_stats(primary, reordered)

    assert merged is not None
    assert [project.key for project in merged.projects] == [
        project.key for project in primary.projects
    ]
    assert merged.projects[0].output == primary.projects[0].output
    assert merged.projects[0].code == reordered.projects[-1].code
    assert "code" in merged.facets
    assert "output" in merged.facets


async def test_projects_paints_output_while_code_worker_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    started = threading.Event()
    release = threading.Event()
    _patch_center(monkeypatch, [])

    def load(
        view: str,
        selected_range: object,
        project_filter: str | None = None,
        macro_focus: str | None = None,
        **kwargs: object,
    ) -> StatisticsViewData:
        del macro_focus
        facets = kwargs.get("facets")
        calls.append((view, facets))
        return _result(
            view,  # type: ignore[arg-type]
            selected_range,  # type: ignore[arg-type]
            project_filter=project_filter,
            facets=(
                set(facets)  # type: ignore[arg-type]
                if isinstance(facets, (set, frozenset))
                else {"output", "runs"}
            ),
        )

    def load_code(
        selected_range: object,
        project_filter: str | None = None,
        *,
        preset: str | None = None,
    ) -> object:
        del preset
        started.set()
        assert release.wait(timeout=5.0)
        result = _result(
            "projects",
            selected_range,  # type: ignore[arg-type]
            project_filter=project_filter,
            facets={"code"},
        )
        assert result.project_stats is not None
        return result.project_stats

    monkeypatch.setattr(sp, "load_statistics_view", load)
    monkeypatch.setattr(sp, "_load_project_code_stats", load_code)

    try:
        async with AcePage() as page:
            _, pane = await _open_statistics(page)
            pane._set_view("projects")
            await page.wait_for(lambda _state: started.is_set())
            assert pane._last_result is not None
            assert pane._last_result.project_stats is not None
            assert pane._code_complete is False
            rendered = _render_plain(pane._projects_renderable(pane._last_result))
            assert "measuring code…" in rendered
            release.set()
            await page.wait_for(lambda _state: pane._code_complete)
            assert pane._last_result.project_stats is not None
            assert "code" in pane._last_result.project_stats.facets
            assert "measuring code…" not in _render_plain(
                pane._projects_renderable(pane._last_result)
            )
    finally:
        release.set()


def test_late_code_result_from_an_old_generation_is_ignored() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "projects"
    pane._load_generation = 2
    pane._last_result = _result("projects", pane._range, facets={"output", "runs"})
    pane._code_complete = False
    stale = _StatisticsLoadResult(
        generation=1,
        kind="code",
        payload=all_projects_view(facets={"code"}),
    )
    worker = SimpleNamespace(result=stale, error=None)
    pane._code_worker = worker  # type: ignore[assignment]

    pane.on_worker_state_changed(
        SimpleNamespace(worker=worker, state=WorkerState.SUCCESS)  # type: ignore[arg-type]
    )

    assert pane._code_complete is False
    assert pane._last_result.project_stats is not None
    assert "code" not in pane._last_result.project_stats.facets


def test_code_failure_keeps_output_and_ends_measuring() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "projects"
    pane._last_result = _result("projects", pane._range, facets={"output", "runs"})
    pane._code_complete = False
    worker = SimpleNamespace(result=None, error=RuntimeError("tokei missing"))
    pane._code_worker = worker  # type: ignore[assignment]

    pane.on_worker_state_changed(
        SimpleNamespace(worker=worker, state=WorkerState.ERROR)  # type: ignore[arg-type]
    )

    assert pane._code_complete is True
    assert pane._last_result is not None
    assert pane._last_result.project_stats is not None
    assert pane._last_result.project_stats.projects[0].output is not None
    assert "code" in pane._last_result.project_stats.facets
    assert "measuring code…" not in _render_plain(
        pane._projects_renderable(pane._last_result)
    )
    assert "tokei missing" in pane._last_error


def test_failed_refresh_retains_the_last_good_projects_report() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "projects"
    good = _result("projects", pane._range)
    pane._last_result = good
    pane._load_generation = 1
    worker = SimpleNamespace(
        result=_StatisticsLoadResult(1, "primary", good),
        error=RuntimeError("store unavailable"),
    )
    pane._worker = worker  # type: ignore[assignment]

    pane.on_worker_state_changed(
        SimpleNamespace(worker=worker, state=WorkerState.ERROR)  # type: ignore[arg-type]
    )

    assert pane._last_result is good
    assert pane._stale_at is not None
    assert "stale ·" in pane._status_text().plain
    assert "load failed" in pane._status_text().plain


def test_compact_and_stacked_projects_renders_match_shared_compose() -> None:
    pane = StatisticsPane(auto_load=False)
    report = one_project_view()
    result = StatisticsViewData(
        view="projects",
        selected_range=pane._range,
        generated_at=NOW.timestamp(),
        project_filter="sase",
        project_stats=report,
    )
    pane._last_result = result
    pane._project_filter = "sase"
    pane._projects_group_by = "model"
    for width in (50, 80, 120):
        pane._projects_body_width = lambda width=width: width  # type: ignore[method-assign]
        ctx = RenderContext(
            width=width,
            color=True,
            unicode=True,
            now=NOW,
            timezone=TZ,
            machine=MACHINE,
        )
        assert _render_plain(pane._projects_renderable(result)) == _render_plain(
            render_project_stats(report, "model", ctx)
        )


def test_load_project_code_stats_is_the_visual_seam() -> None:
    assert callable(_load_project_code_stats)
