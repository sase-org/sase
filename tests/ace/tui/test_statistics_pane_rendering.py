"""Rendering coverage for the Statistics pane."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.ranges import StatsRange
from sase.stats.views import build_statistics_views

from tests.ace.tui._statistics_pane_helpers import (
    activity_payload as _activity_payload,
    render_plain as _render_plain,
    result as _result,
    run_payload as _run_payload,
)
from tests._project_display_case import ProjectDisplayCase


def test_renderers_use_projected_labels_and_canonical_project_colors(
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    widgets_key = project_display_case.project_key
    patch_key, patch_label = project_display_case.patch("statistics-projects")
    snapshot = project_display_case.snapshot
    payload = _run_payload(StatsRange(0, 100, "absolute", "Test"), "project")
    payload["workspaces"][0]["project"] = widgets_key
    payload["work"]["projects"][0]["project"] = widgets_key
    payload["work"]["changespecs"][0].update(  # legacy stats wire key
        {"project": widgets_key, "name": patch_key}
    )
    payload["runtime_groups"][0]["group"] = widgets_key
    views = build_statistics_views(
        payload,
        _activity_payload(),
        project_display_snapshot=snapshot,
    )
    color_keys: list[str] = []

    def color_for(key: str, *, among: object = None) -> str:
        del among
        color_keys.append(key)
        return "#87D7FF"

    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_views.project_accent",
        color_for,
    )
    pane = StatisticsPane(auto_load=False)
    projects_result = _result(
        "projects",
        pane._range,
        project_display_case=project_display_case,
    )

    overview = _render_plain(pane._overview_renderable(views.overview))
    activity = _render_plain(pane._activity_renderable(views.activity))
    pane._projects_group_by = "project"
    by_project = _render_plain(pane._projects_renderable(projects_result))
    pane._projects_group_by = "repo"
    by_repo = _render_plain(pane._projects_renderable(projects_result))
    pane._projects_group_by = "model"
    by_model = _render_plain(pane._projects_renderable(projects_result))
    pane._projects_group_by = "patch"
    by_patch = _render_plain(pane._projects_renderable(projects_result))

    assert project_display_case.project_label in overview
    assert f"{project_display_case.project_label} · 15" in activity
    assert views.runtime.rows[0].group_label == project_display_case.project_label
    assert project_display_case.project_label in by_project
    assert project_display_case.project_label in by_repo
    assert patch_label in by_patch
    assert widgets_key not in "\n".join(
        (overview, activity, by_project, by_repo, by_model, by_patch)
    )
    assert widgets_key in color_keys


def test_overview_bucket_panel_discloses_grouping_only_when_aggregated() -> None:
    default_range = StatsRange(0, 7_200, "absolute", "Test")
    default_payload = _run_payload(default_range, "agent")
    default_views = build_statistics_views(default_payload, _activity_payload())
    pane = StatisticsPane(auto_load=False)

    default_overview = _render_plain(pane._overview_renderable(default_views.overview))

    assert "Runs over time" in default_overview
    assert "buckets" not in default_overview

    grouped_payload = _run_payload(default_range, "agent")
    grouped_payload["bucket_seconds"] = 86_400
    grouped_payload["buckets"] = [
        {"start_ts": index * 86_400, "runs": 1 if index % 10 == 0 else 0}
        for index in range(200)
    ]
    grouped_views = build_statistics_views(grouped_payload, _activity_payload())

    grouped_overview = _render_plain(pane._overview_renderable(grouped_views.overview))

    assert "Runs over time · 2-day buckets" in grouped_overview


def test_all_project_plan_and_question_values_need_no_scope_markers() -> None:
    pane = StatisticsPane(auto_load=False)
    view = _result(pane._view, pane._range).views

    group = pane._plans_questions_renderable(
        view.plans_questions, requested_start_ts=pane._range.start_ts
    )
    columns = group.renderables[-1]
    rendered = _render_plain(group)

    assert [panel.title for panel in columns.renderables] == ["Plans", "Questions"]
    assert "all projects" not in rendered
    assert (
        "Proposed  3  ·  Approved  2  ·  Rejected  0  ·  Feedback  0  ·  Pending  1"
    ) in rendered
    assert "Sessions  2  ·  Asking agents  2  ·  Questions  3" in rendered


def test_project_filtered_plan_and_question_values_need_no_scope_markers() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._project_filter = "sase"
    view = _result(pane._view, pane._range).views

    group = pane._plans_questions_renderable(
        view.plans_questions, requested_start_ts=pane._range.start_ts
    )
    columns = group.renderables[-1]
    rendered = _render_plain(group)

    assert [panel.title for panel in columns.renderables] == ["Plans", "Questions"]
    assert (
        "Proposed  3  ·  Approved  2  ·  Rejected  0  ·  Feedback  0  ·  Pending  1"
    ) in rendered
    assert "Sessions  2  ·  Asking agents  2" in rendered
    assert "all projects" not in rendered
    assert "Mean phases per epic: 5.00" in rendered
    assert "Mean questions per session: 1.50" in rendered


@pytest.mark.parametrize(
    ("group_by", "distinctive_copy"),
    (
        ("usage", ("Refs", "Agents", "Last used")),
        ("model", ("Macro → Model", "gpt-5.6", "(no model recorded)")),
        ("project", ("Macro → Project", "SASE", "Core")),
        ("pairing", ("Macro → Used with", "#gh", "(used alone)")),
    ),
)
def test_macros_grouping_modes_render_distinctive_columns_and_rows(
    group_by: str,
    distinctive_copy: tuple[str, ...],
) -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "macros"
    pane._macros_group_by = group_by  # type: ignore[assignment]
    result = _result(
        "macros",
        pane._range,
        project_display_snapshot=ProjectDisplaySnapshot(
            {"sase": "SASE", "core": "Core"}
        ),
    )

    rendered = _render_plain(pane._view_renderable(result))

    assert (
        "2 macros · 4 runs referenced · 5 references · 2 runs without macros (33.3%)"
    ) in rendered
    assert all(copy in rendered for copy in distinctive_copy)
    collapsed = " ".join(rendered.split())
    assert "Scope = launch-boundary references only" in collapsed


def test_swarm_rows_and_focus_header_label_the_swarm_kind() -> None:
    pane = StatisticsPane(auto_load=False)
    payload = _run_payload(pane._range, "tribe")
    payload["macros"]["rows"][0].update(
        {"name": "research_swarm", "kind": "swarm", "tags": []}
    )
    views = build_statistics_views(payload, _activity_payload())

    rendered = _render_plain(pane._macros_usage_renderable(views.macros))

    assert "#research_swarm  swarm" in rendered


def test_plans_questions_render_feedback_and_coverage_floor() -> None:
    pane = StatisticsPane(auto_load=False)
    payload = _activity_payload()
    payload["coverage_start_ts"] = pane._range.start_ts + 60
    views = build_statistics_views(_run_payload(pane._range, "tribe"), payload)

    rendered = _render_plain(
        pane._plans_questions_renderable(
            views.plans_questions,
            requested_start_ts=pane._range.start_ts,
        )
    )

    assert "Feedback  0" in rendered
    assert "Plan/question data begins" in rendered


def test_macro_focus_header_labels_the_swarm_kind() -> None:
    pane = StatisticsPane(auto_load=False)
    payload = _run_payload(pane._range, "tribe")
    payload["macros"]["focus"] = {
        "name": "research_swarm",
        "found": True,
        "kind": "swarm",
        "tags": [],
        "runs": 4,
        "references": 4,
        "distinct_agents": 4,
        "completed": 4,
        "failed": 0,
        "success_rate": 1.0,
        "total_runtime_seconds": 480.0,
        "mean_runtime_seconds": 120.0,
        "first_run_ts": pane._range.start_ts,
        "last_run_ts": pane._range.start_ts + 60,
        "models": [],
        "projects": [],
        "partners": [{"name": "gh", "count": 4}],
        "providers": [],
        "tribes": [],
        "buckets": [],
    }
    views = build_statistics_views(payload, _activity_payload())
    focus = views.macros.focus
    assert focus is not None

    rendered = _render_plain(pane._macro_focus_header(focus))

    assert "#research_swarm  swarm" in rendered


def test_commits_tile_shows_distinct_agents_and_committing_runs() -> None:
    pane = StatisticsPane(auto_load=False)
    result = _result("overview", pane._range)
    captured: dict[str, object] = {}
    pane._update_static = captured.__setitem__  # type: ignore[method-assign]
    pane._configure_overview_tile_widgets = lambda: None  # type: ignore[method-assign]
    pane._tile_width = lambda: 24  # type: ignore[method-assign]

    pane._paint_overview_tiles(result)

    rendered = _render_plain(captured["#statistics-tile-2"])
    assert "3 agents · 3 runs" in rendered
    assert "7" in rendered


def test_projects_renderable_matches_shared_compose_at_the_same_context() -> None:
    from sase.stats.loader import StatisticsViewData
    from sase.stats.render.compose import render_project_stats
    from sase.stats.render.context import RenderContext
    from tests.stats._project_render_fixtures import MACHINE, NOW, TZ, all_projects_view

    pane = StatisticsPane(auto_load=False)
    report = all_projects_view()
    result = StatisticsViewData(
        view="projects",
        selected_range=pane._range,
        generated_at=NOW.timestamp(),
        project_stats=report,
    )
    pane._last_result = result
    pane._projects_group_by = "project"
    pane._projects_body_width = lambda: 120  # type: ignore[method-assign]
    ctx = RenderContext(
        width=120,
        color=True,
        unicode=True,
        now=NOW,
        timezone=TZ,
        machine=MACHINE,
    )

    assert _render_plain(pane._projects_renderable(result)) == _render_plain(
        render_project_stats(report, "project", ctx)
    )


def test_macros_drilldown_discloses_per_row_truncation() -> None:
    pane = StatisticsPane(auto_load=False)
    payload = _run_payload(pane._range, "tribe")
    payload["macros"]["rows"][0]["models_truncated"] = 4
    views = build_statistics_views(payload, _activity_payload())

    rendered = _render_plain(
        pane._macros_drilldown_renderable(views.macros, dimension="model")
    )

    assert "+4 more not shown" in rendered
    assert rendered.count("more not shown") == 1


def test_macros_legend_splits_share_denominators() -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "macros"
    rendered = " ".join(
        _render_plain(pane._macros_renderable(_result("macros", pane._range))).split()
    )

    assert "Share = share of runs that referenced any macro" in rendered
    assert "Child share = share of that macro's own runs" in rendered


def test_macros_truncation_is_explicit() -> None:
    pane = StatisticsPane(auto_load=False)
    payload = _run_payload(pane._range, "tribe")
    payload["macros"]["truncated_rows"] = 7
    views = build_statistics_views(payload, _activity_payload())

    rendered = _render_plain(pane._macros_usage_renderable(views.macros))

    assert "7 more macros not shown." in rendered


def test_macros_unavailable_and_no_reference_states_use_effective_keys() -> None:
    pane = StatisticsPane(auto_load=False)
    unavailable = _run_payload(pane._range, "tribe")
    unavailable.pop("macros")
    unavailable_result = _result(
        "macros",
        pane._range,
    )
    unavailable_result = unavailable_result.__class__(
        view="macros",
        selected_range=pane._range,
        generated_at=unavailable_result.generated_at,
        views=build_statistics_views(unavailable, _activity_payload()),
    )
    pane._view = "macros"

    rendered = _render_plain(pane._view_renderable(unavailable_result))
    assert "Macro statistics unavailable" in rendered
    assert "Press r to refresh" in rendered

    empty_payload = _run_payload(pane._range, "tribe")
    empty_payload["macros"].update(
        {
            "runs_with_macros": 0,
            "runs_without_macros": 6,
            "distinct_macros": 0,
            "total_references": 0,
            "rows": [],
        }
    )
    empty_result = unavailable_result.__class__(
        view="macros",
        selected_range=pane._range,
        generated_at=unavailable_result.generated_at,
        views=build_statistics_views(empty_payload, _activity_payload()),
    )
    rendered = _render_plain(pane._view_renderable(empty_result))
    assert f"No prompt in {pane._range.display_label} referenced a macro." in rendered
    assert "Press t to widen the range." in rendered
