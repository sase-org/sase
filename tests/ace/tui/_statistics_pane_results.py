"""Build deterministic Statistics pane view results for tests."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats import PerfView, build_perf_view
from sase.stats.perf_query import PerfGroupBy
from sase.stats.project.view import ProjectStatsView
from sase.stats.query import RuntimeGroupBy
from sase.stats.ranges import StatsRange
from sase.stats.views import build_statistics_views
from sase.ace.tui.modals.statistics_pane_data import StatisticsView, StatisticsViewData
from tests.ace.tui._statistics_pane_payloads import (
    NOW,
    activity_payload as build_activity_payload,
    run_payload,
)
from tests._project_display_case import ProjectDisplayCase

_PROJECTS_PRIMARY_FACETS: frozenset[str] = frozenset({"output", "runs", "code"})


def _pane_project_stats(
    *,
    project_filter: str | None = None,
    empty: bool = False,
    facets: set[str] | frozenset[str] | None = None,
    project_display_case: ProjectDisplayCase | None = None,
) -> ProjectStatsView:
    """Build a Projects report whose keys match the pane's composite fixtures."""
    from tests.stats._project_render_fixtures import build_view
    from tests.stats._project_render_projects import bob_project, sase_project

    resolved_facets = (
        set(facets) if facets is not None else set(_PROJECTS_PRIMARY_FACETS)
    )
    if empty:
        return build_view(projects=[], facets=resolved_facets)
    sase = sase_project()
    if project_display_case is not None:
        sase["key"] = project_display_case.project_key
        sase["label"] = project_display_case.project_label
        _patch_key, patch_label = project_display_case.patch("statistics-projects")
        if sase["patches"]:
            sase["patches"][0] = {**sase["patches"][0], "name": patch_label}
    else:
        sase["key"] = "sase"
        sase["label"] = "sase"
    core = bob_project()
    core["key"] = "core"
    core["label"] = "core"
    rows = [sase, core]
    if project_filter is not None:
        rows = [row for row in rows if row["key"] == project_filter]
    if "code" not in resolved_facets:
        for row in rows:
            row["code"] = None
    view = build_view(
        projects=rows,
        facets=resolved_facets,
        project_refs=(project_filter,) if project_filter else (),
    )
    if "code" not in resolved_facets:
        view = replace(
            view,
            projects=tuple(replace(project, code=None) for project in view.projects),
            portfolio=replace(view.portfolio, code=None),
        )
    return view


def footprint_report(
    *,
    lens: str = "map",
    actor: str = "you",
    area: str | None = None,
    empty: bool = False,
) -> dict[str, Any]:
    """Build a deterministic map/lens response for Statistics pane tests."""
    areas = [
        {
            "area": "cli.bead",
            "total": 10,
            "used": 6,
            "used_pct": 60,
            "recency_7d": 2,
            "recency_30d": 2,
            "recency_window": 2,
            "recency_none": 3,
            "recency_not_measured": 1,
        },
        {
            "area": "tui.statistics",
            "total": 12,
            "used": 7,
            "used_pct": 58,
            "recency_7d": 3,
            "recency_30d": 2,
            "recency_window": 2,
            "recency_none": 4,
            "recency_not_measured": 1,
        },
        {
            "area": "mobile",
            "total": 3,
            "used": 0,
            "used_pct": 0,
            "recency_7d": 0,
            "recency_30d": 0,
            "recency_window": 0,
            "recency_none": 0,
            "recency_not_measured": 3,
        },
    ]
    features = [
        {
            "id": "cli:bead.list",
            "label": "bead list",
            "ns": "cli",
            "area": "cli.bead",
            "kind": "command",
            "state": "used",
            "uses": {"human": 9, "agent": 4, "automation": 0},
            "days_used": 5,
            "last_used_day": "2026-10-27",
            "via": {"cli": 13},
            "loc": 520,
        },
        {
            "id": "cli:bead.close",
            "label": "bead close",
            "ns": "cli",
            "area": "cli.bead",
            "kind": "command",
            "state": "no_recorded_use",
            "uses": {"human": 0, "agent": 0, "automation": 0},
            "days_used": 0,
            "last_used_day": None,
            "via": {},
            "loc": 210,
        },
        {
            "id": "tui:statistics.cycle_range",
            "label": "Cycle Statistics range",
            "ns": "tui",
            "area": "tui.statistics",
            "kind": "action",
            "state": "used",
            "uses": {"human": 3, "agent": 0, "automation": 0},
            "days_used": 2,
            "last_used_day": "2026-10-26",
            "via": {"key": 3},
            "loc": 30,
        },
        {
            "id": "plugin:mobile",
            "label": "Mobile integration",
            "ns": "plugin",
            "area": "mobile",
            "kind": "plugin",
            "state": "not_measured",
            "uses": {"human": 0, "agent": 0, "automation": 0},
            "days_used": 0,
            "last_used_day": None,
            "via": {},
            "loc": 0,
        },
    ]
    if area is not None:
        features = [row for row in features if row["area"] == area]
    return {
        "schema_version": 1,
        "header": {
            "actor": actor,
            "window_days": 60,
            "observed_active_days": {"cli": 12, "tui": 3, "macro": 2},
            "recording_since": "2026-10-01",
            "gate_met": False,
            "gate_active_days": 12,
            "gate_required_days": 30,
        },
        "tiles": {
            "total": 0 if empty else 25,
            "used": 0 if empty else 13,
            "candidates": 0 if empty else 3,
            "candidates_preview": True,
            "rare_by_design": 0 if empty else 2,
            "agent_only": 0 if empty else 1,
            "not_measured": 0 if empty else 5,
        },
        "areas": [] if empty else areas,
        "rows": [] if empty else features,
        "coverage": [
            {
                "surface": "cli",
                "measured_days": 12,
                "active_days": 12,
                "torn": 0,
                "dropped": 1,
                "unknown_ids": 2,
                "incomplete_days": 0,
            },
            {
                "surface": "tui",
                "measured_days": 3,
                "active_days": 3,
                "torn": 1,
                "dropped": 0,
                "unknown_ids": 0,
                "incomplete_days": 1,
            },
        ],
    }


def perf_view(
    selected_range: StatsRange,
    *,
    group_by: PerfGroupBy = "subsystem",
) -> PerfView:
    from tests.stats._views_payloads import perf_logs_payload, perf_telemetry_payload

    return build_perf_view(
        perf_logs_payload(),
        perf_telemetry_payload(),
        selected_range=selected_range,
        group_by=group_by,
    )


def result(
    view: StatisticsView,
    selected_range: StatsRange,
    *,
    empty: bool = False,
    runs_empty: bool = False,
    project_filter: str | None = None,
    project_display_snapshot: ProjectDisplaySnapshot | None = None,
    project_display_case: ProjectDisplayCase | None = None,
    macro_focus: str | None = None,
    runtime_group_by: RuntimeGroupBy = "tribe",
    perf_group_by: PerfGroupBy = "subsystem",
    perf: PerfView | None = None,
    facets: set[str] | frozenset[str] | None = None,
    footprint_lens: str = "map",
    footprint_actor: str = "you",
    footprint_area: str | None = None,
) -> StatisticsViewData:
    if view == "footprint":
        return StatisticsViewData(
            view=view,
            selected_range=selected_range,
            generated_at=NOW,
            project_filter=project_filter,
            macro_focus=macro_focus,
            footprint=footprint_report(
                lens=footprint_lens,
                actor=footprint_actor,
                area=footprint_area,
                empty=empty,
            ),
            footprint_lens=footprint_lens,
            footprint_actor=footprint_actor,
            footprint_area=footprint_area,
        )
    runs_payload: dict[str, Any] = (
        {} if empty else run_payload(selected_range, runtime_group_by)
    )
    if runs_empty and not empty:
        runs_payload = {"totals": {"runs": 0}}
    if runs_payload and macro_focus is not None:
        found = macro_focus == "split_file"
        runs_payload["macros"]["focus"] = {
            "name": macro_focus,
            "found": found,
            "kind": "part" if found else "unknown",
            "tags": ["files"] if found else [],
            "runs": 3 if found else 0,
            "references": 4 if found else 0,
            "distinct_agents": 2 if found else 0,
            "completed": 2 if found else 0,
            "failed": 1 if found else 0,
            "success_rate": 2 / 3 if found else 0.0,
            "total_runtime_seconds": 360.0 if found else 0.0,
            "mean_runtime_seconds": 120.0 if found else None,
            "first_run_ts": NOW - 3_600 if found else 0.0,
            "last_run_ts": NOW if found else 0.0,
            "models": [{"name": "gpt-5.6", "count": 2}],
            "projects": [{"name": "sase", "count": 2}],
            "partners": [{"name": "gh", "count": 2}],
            "providers": [{"name": "codex", "count": 2}],
            "tribes": [{"name": "tui", "count": 2}],
            "buckets": [
                {"start_ts": selected_range.start_ts, "runs": 1},
                {"start_ts": selected_range.start_ts + 86_400, "runs": 2},
            ],
        }
    if project_display_case is not None and runs_payload:
        runs_payload["workspaces"][0]["project"] = project_display_case.project_key
        runs_payload["work"]["projects"][0]["project"] = (
            project_display_case.project_key
        )
        runs_payload["work"]["changespecs"][0].update(  # legacy stats wire key
            {
                "project": project_display_case.project_key,
                "name": project_display_case.patch_key,
            }
        )
        if runtime_group_by == "project":
            runs_payload["runtime_groups"][0]["group"] = (
                project_display_case.project_key
            )
        elif runtime_group_by == "patch":
            runs_payload["runtime_groups"][0]["group"] = project_display_case.patch_key
    activity_payload = {} if empty else build_activity_payload()
    display_snapshot = (
        project_display_snapshot
        if project_display_snapshot is not None
        else (
            project_display_case.snapshot
            if project_display_case is not None
            else ProjectDisplaySnapshot()
        )
    )
    resolved_perf = perf
    if resolved_perf is None and view == "perf":
        resolved_perf = perf_view(selected_range, group_by=perf_group_by)
    if view == "projects":
        return StatisticsViewData(
            view=view,
            selected_range=selected_range,
            generated_at=NOW,
            views=None,
            project_filter=project_filter,
            macro_focus=macro_focus,
            project_display_snapshot=display_snapshot,
            project_stats=_pane_project_stats(
                project_filter=project_filter,
                empty=empty,
                facets=facets,
                project_display_case=project_display_case,
            ),
        )
    return StatisticsViewData(
        view=view,
        selected_range=selected_range,
        generated_at=NOW,
        views=build_statistics_views(
            runs_payload,
            activity_payload,
            project_display_snapshot=display_snapshot,
            current_runner_limit=2,
        ),
        project_filter=project_filter,
        macro_focus=macro_focus,
        project_display_snapshot=display_snapshot,
        perf=resolved_perf,
    )
