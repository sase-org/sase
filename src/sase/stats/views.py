"""Stable facade for immutable, presentation-ready Statistics views."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import tzinfo

from sase.core.time import get_timezone
from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats._runner_view import build_runners_view
from sase.stats._view_builders import (
    build_activity_view,
    build_overview_view,
    build_plans_questions_view,
    build_projects_view,
    build_providers_view,
    build_runs_view,
    build_runtime_view,
)
from sase.stats._view_models import (
    ActivityView,
    OverviewView,
    PlansQuestionsView,
    ProjectsView,
    ProvidersView,
    RunnersView,
    RunsView,
    RuntimeView,
)
from sase.stats._view_payload import Payload, integer, mapping


@dataclass(frozen=True, slots=True)
class StatisticsViews:
    """All eight views built from one run and one activity response."""

    start_ts: int
    end_ts: int
    empty: bool
    overview: OverviewView
    runs: RunsView
    projects: ProjectsView
    providers: ProvidersView
    runtime: RuntimeView
    activity: ActivityView
    plans_questions: PlansQuestionsView
    runners: RunnersView


def build_statistics_views(
    run_payload: Payload,
    activity_payload: Payload,
    *,
    previous_run_payload: Payload | None = None,
    timezone: tzinfo | None = None,
    project_display_snapshot: ProjectDisplaySnapshot | None = None,
    current_runner_limit: int | None = None,
) -> StatisticsViews:
    """Build every Statistics view without performing I/O."""
    display_snapshot = (
        project_display_snapshot
        if project_display_snapshot is not None
        else ProjectDisplaySnapshot()
    )
    resolved_timezone = timezone or get_timezone()
    totals = mapping(run_payload.get("totals"))
    projects = build_projects_view(run_payload, display_snapshot)
    return StatisticsViews(
        start_ts=integer(run_payload.get("start_ts")),
        end_ts=integer(run_payload.get("end_ts")),
        empty=integer(totals.get("runs")) == 0,
        overview=build_overview_view(
            run_payload,
            activity_payload,
            previous_run_payload=previous_run_payload,
            timezone=resolved_timezone,
            projects=projects,
        ),
        runs=build_runs_view(run_payload),
        projects=projects,
        providers=build_providers_view(run_payload),
        runtime=build_runtime_view(run_payload, display_snapshot),
        activity=build_activity_view(
            run_payload,
            activity_payload,
            display_snapshot,
        ),
        plans_questions=build_plans_questions_view(run_payload, activity_payload),
        runners=build_runners_view(
            run_payload,
            current_runner_limit=current_runner_limit,
            timezone=resolved_timezone,
        ),
    )


__all__ = [
    "StatisticsViews",
    "build_statistics_views",
]
