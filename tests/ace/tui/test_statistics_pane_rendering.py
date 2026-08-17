"""Rendering coverage for the Statistics pane."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.ranges import StatsRange
from sase.stats.views import build_statistics_views

from tests.ace.tui._statistics_pane_helpers import (
    _activity_payload,
    _render_plain,
    _result,
    _run_payload,
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

    def color_for(key: str) -> str:
        color_keys.append(key)
        return "#87D7FF"

    monkeypatch.setattr(
        "sase.ace.tui.modals.statistics_pane_projects.categorical_color",
        color_for,
    )
    pane = StatisticsPane(auto_load=False)

    overview = _render_plain(pane._overview_renderable(views.overview))
    activity = _render_plain(pane._activity_renderable(views.activity))
    project_surfaces: list[str] = []
    for group_by in ("project", "patch", "drilldown"):
        pane._projects_group_by = group_by  # type: ignore[assignment]
        project_surfaces.append(
            _render_plain(pane._projects_renderable(views.projects))
        )

    assert project_display_case.project_label in overview
    assert f"{project_display_case.project_label} · 15" in activity
    assert views.runtime.rows[0].group_label == project_display_case.project_label
    assert all(
        project_display_case.project_label in rendered for rendered in project_surfaces
    )
    assert patch_label in "\n".join(project_surfaces)
    assert widgets_key not in "\n".join((overview, activity, *project_surfaces))
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
        ("model", ("XPrompt → Model", "gpt-5.6", "(no model recorded)")),
        ("project", ("XPrompt → Project", "SASE", "Core")),
        ("pairing", ("XPrompt → Used with", "#gh", "(used alone)")),
    ),
)
def test_xprompts_grouping_modes_render_distinctive_columns_and_rows(
    group_by: str,
    distinctive_copy: tuple[str, ...],
) -> None:
    pane = StatisticsPane(auto_load=False)
    pane._view = "xprompts"
    pane._xprompts_group_by = group_by  # type: ignore[assignment]
    result = _result(
        "xprompts",
        pane._range,
        project_display_snapshot=ProjectDisplaySnapshot(
            {"sase": "SASE", "core": "Core"}
        ),
    )

    rendered = _render_plain(pane._view_renderable(result))

    assert (
        "2 xprompts · 4 runs referenced · 5 references · "
        "2 runs without xprompts (33.3%)"
    ) in rendered
    assert all(copy in rendered for copy in distinctive_copy)
    assert "Scope = launch-boundary references only" in rendered


def test_swarm_rows_and_focus_header_label_the_swarm_kind() -> None:
    pane = StatisticsPane(auto_load=False)
    payload = _run_payload(pane._range, "tribe")
    payload["xprompts"]["rows"][0].update(
        {"name": "research_swarm", "kind": "swarm", "tags": []}
    )
    views = build_statistics_views(payload, _activity_payload())

    rendered = _render_plain(pane._xprompts_usage_renderable(views.xprompts))

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


def test_xprompt_focus_header_labels_the_swarm_kind() -> None:
    pane = StatisticsPane(auto_load=False)
    payload = _run_payload(pane._range, "tribe")
    payload["xprompts"]["focus"] = {
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
    focus = views.xprompts.focus
    assert focus is not None

    rendered = _render_plain(pane._xprompt_focus_header(focus))

    assert "#research_swarm  swarm" in rendered


def test_xprompts_truncation_is_explicit() -> None:
    pane = StatisticsPane(auto_load=False)
    payload = _run_payload(pane._range, "tribe")
    payload["xprompts"]["truncated_rows"] = 7
    views = build_statistics_views(payload, _activity_payload())

    rendered = _render_plain(pane._xprompts_usage_renderable(views.xprompts))

    assert "7 more xprompts not shown." in rendered


def test_xprompts_unavailable_and_no_reference_states_use_effective_keys() -> None:
    pane = StatisticsPane(auto_load=False)
    unavailable = _run_payload(pane._range, "tribe")
    unavailable.pop("xprompts")
    unavailable_result = _result(
        "xprompts",
        pane._range,
    )
    unavailable_result = unavailable_result.__class__(
        view="xprompts",
        selected_range=pane._range,
        generated_at=unavailable_result.generated_at,
        views=build_statistics_views(unavailable, _activity_payload()),
    )
    pane._view = "xprompts"

    rendered = _render_plain(pane._view_renderable(unavailable_result))
    assert "XPrompt statistics unavailable" in rendered
    assert "Press r to refresh" in rendered

    empty_payload = _run_payload(pane._range, "tribe")
    empty_payload["xprompts"].update(
        {
            "runs_with_xprompts": 0,
            "runs_without_xprompts": 6,
            "distinct_xprompts": 0,
            "total_references": 0,
            "rows": [],
        }
    )
    empty_result = unavailable_result.__class__(
        view="xprompts",
        selected_range=pane._range,
        generated_at=unavailable_result.generated_at,
        views=build_statistics_views(empty_payload, _activity_payload()),
    )
    rendered = _render_plain(pane._view_renderable(empty_result))
    assert (
        f"No prompt in {pane._range.display_label} referenced an xprompt." in rendered
    )
    assert "Press t to widen the range." in rendered
