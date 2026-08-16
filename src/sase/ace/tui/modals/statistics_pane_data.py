"""Off-thread query and model building for the Admin Center Statistics pane."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from sase.project_display_names import (
    ProjectDisplaySnapshot,
    load_project_display_snapshot,
)
from sase.stats import PerfView, build_perf_view
from sase.stats.perf_query import (
    PerfGroupBy,
    query_perf_logs,
    query_perf_telemetry,
)
from sase.stats.query import RuntimeGroupBy, query_activity_stats, query_run_stats
from sase.stats.ranges import StatsRange
from sase.stats.views import StatisticsViews, build_statistics_views
from sase.telemetry._config import HealthThresholds

StatisticsView = Literal[
    "overview",
    "runners",
    "projects",
    "providers",
    "activity",
    "xprompts",
    "plans_questions",
    "perf",
]
ProjectsGroupBy = Literal["project", "patch", "drilldown"]
XPromptsGroupBy = Literal["usage", "model", "project", "pairing"]
_FIXED_RUNTIME_GROUP_BY: RuntimeGroupBy = "tribe"

VIEW_ORDER: tuple[StatisticsView, ...] = (
    "overview",
    "runners",
    "projects",
    "providers",
    "activity",
    "xprompts",
    "plans_questions",
    "perf",
)
VIEW_LABELS: dict[StatisticsView, str] = {
    "overview": "Overview",
    "runners": "Runners",
    "projects": "Projects",
    "providers": "Providers",
    "activity": "Activity",
    "xprompts": "XPrompts",
    "plans_questions": "Plans & Questions",
    "perf": "Perf",
}
VIEW_COMPACT_LABELS: dict[StatisticsView, str] = {
    **VIEW_LABELS,
    "plans_questions": "Plans/Q",
}
VIEW_MICRO_LABELS: dict[StatisticsView, str] = {
    "overview": "Ovr",
    "runners": "Rnrs",
    "projects": "Proj",
    "providers": "Prov",
    "activity": "Act",
    "xprompts": "XP",
    "plans_questions": "P&Q",
    "perf": "Prf",
}
VIEW_DESCRIPTIONS: dict[StatisticsView, str] = {
    "overview": "Totals and trends across runs, commits, plans, and questions.",
    "runners": "Runner occupancy, concurrency trends, and current-limit context.",
    "projects": "Run, Patch, commit, and runtime activity by project.",
    "providers": "Provider, model, and effort usage with success and runtime measures.",
    "activity": "Skill and memory usage across agents in the selected scope.",
    "xprompts": (
        "XPrompt usage across prompts, with model, project, and co-usage breakdowns."
    ),
    "plans_questions": "Plan decisions, epic structure, and agent question patterns.",
    "perf": (
        "TUI responsiveness, launch and agent latency, and the health of the "
        "data behind these numbers."
    ),
}

PERF_GROUP_ORDER: tuple[PerfGroupBy, ...] = (
    "subsystem",
    "provider",
    "workflow",
)
PROJECTS_GROUP_ORDER: tuple[ProjectsGroupBy, ...] = (
    "project",
    "patch",
    "drilldown",
)
XPROMPTS_GROUP_ORDER: tuple[XPromptsGroupBy, ...] = (
    "usage",
    "model",
    "project",
    "pairing",
)


def statistics_view_supports_grouping(view: StatisticsView) -> bool:
    """Return whether ``view`` exposes a configurable grouping strategy."""
    return view in ("projects", "xprompts", "perf")


@dataclass(frozen=True, slots=True)
class StatisticsViewData:
    """One immutable result painted by :class:`StatisticsPane`."""

    view: StatisticsView
    selected_range: StatsRange
    generated_at: float
    views: StatisticsViews
    project_filter: str | None = None
    xprompt_focus: str | None = None
    project_display_snapshot: ProjectDisplaySnapshot = field(
        default_factory=ProjectDisplaySnapshot
    )
    perf: PerfView | None = None


def load_statistics_view(
    view: StatisticsView,
    selected_range: StatsRange,
    project_filter: str | None = None,
    xprompt_focus: str | None = None,
    perf_group_by: PerfGroupBy = "subsystem",
) -> StatisticsViewData:
    """Query composite bindings and build all view models off-thread."""
    from sase.config.core import get_max_running_agents
    from sase.telemetry._config import get_telemetry_config as load_telemetry_config

    project_display_snapshot = load_project_display_snapshot()
    current_runner_limit = get_max_running_agents()
    run_payload = query_run_stats(
        start_ts=selected_range.start_ts,
        end_ts=selected_range.end_ts,
        runtime_group_by=_FIXED_RUNTIME_GROUP_BY,
        project=project_filter,
        xprompt_focus=xprompt_focus,
    )
    activity_payload = query_activity_stats(
        start_ts=selected_range.start_ts,
        end_ts=selected_range.end_ts,
        project=project_filter,
    )
    previous_run_payload = None
    if selected_range.start_ts > 0:
        window_seconds = selected_range.end_ts - selected_range.start_ts
        previous_run_payload = query_run_stats(
            start_ts=selected_range.start_ts - window_seconds,
            end_ts=selected_range.start_ts,
            runtime_group_by=_FIXED_RUNTIME_GROUP_BY,
            top_n=1,
            project=project_filter,
        )
    generated_at = time.time()
    perf = None
    if view == "perf":
        perf = _load_perf_view(
            selected_range,
            group_by=perf_group_by,
            now=generated_at,
            health_thresholds=load_telemetry_config().health_thresholds,
        )
    return StatisticsViewData(
        view=view,
        selected_range=selected_range,
        generated_at=generated_at,
        views=build_statistics_views(
            run_payload,
            activity_payload,
            previous_run_payload=previous_run_payload,
            project_display_snapshot=project_display_snapshot,
            current_runner_limit=current_runner_limit,
        ),
        project_filter=project_filter,
        xprompt_focus=xprompt_focus,
        project_display_snapshot=project_display_snapshot,
        perf=perf,
    )


def _load_perf_view(
    selected_range: StatsRange,
    *,
    group_by: PerfGroupBy,
    now: float,
    health_thresholds: HealthThresholds,
) -> PerfView:
    perf_payload = query_perf_logs(
        start_ts=selected_range.start_ts,
        end_ts=selected_range.end_ts,
    )
    telemetry_payload = query_perf_telemetry(
        start_ts=selected_range.start_ts,
        end_ts=selected_range.end_ts,
        group_by=group_by,
    )
    previous_perf_payload = None
    previous_telemetry_payload = None
    if selected_range.start_ts > 0:
        window_seconds = selected_range.end_ts - selected_range.start_ts
        previous_start = selected_range.start_ts - window_seconds
        previous_perf_payload = query_perf_logs(
            start_ts=previous_start,
            end_ts=selected_range.start_ts,
        )
        previous_telemetry_payload = query_perf_telemetry(
            start_ts=previous_start,
            end_ts=selected_range.start_ts,
            group_by=group_by,
        )
    return build_perf_view(
        perf_payload,
        telemetry_payload,
        selected_range=selected_range,
        previous_perf_payload=previous_perf_payload,
        previous_telemetry_payload=previous_telemetry_payload,
        group_by=group_by,
        now=now,
        health_thresholds=health_thresholds,
    )


__all__ = [
    "PERF_GROUP_ORDER",
    "PROJECTS_GROUP_ORDER",
    "XPROMPTS_GROUP_ORDER",
    "VIEW_DESCRIPTIONS",
    "VIEW_COMPACT_LABELS",
    "VIEW_LABELS",
    "VIEW_MICRO_LABELS",
    "VIEW_ORDER",
    "StatisticsView",
    "StatisticsViewData",
    "ProjectsGroupBy",
    "PerfGroupBy",
    "XPromptsGroupBy",
    "load_statistics_view",
    "statistics_view_supports_grouping",
]
