"""Off-thread query and model building for the Admin Center Statistics pane."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from sase.project_display_names import (
    ProjectDisplaySnapshot,
    load_project_display_snapshot,
)
from sase.stats.query import RuntimeGroupBy, query_activity_stats, query_run_stats
from sase.stats.ranges import StatsRange
from sase.stats.views import StatisticsViews, build_statistics_views

StatisticsView = Literal[
    "overview",
    "runs",
    "runners",
    "projects",
    "providers",
    "runtime",
    "activity",
    "xprompts",
    "plans_questions",
]
ProjectsGroupBy = Literal["project", "changespec", "drilldown"]
XPromptsGroupBy = Literal["usage", "model", "project", "pairing"]

VIEW_ORDER: tuple[StatisticsView, ...] = (
    "overview",
    "runs",
    "runners",
    "projects",
    "providers",
    "runtime",
    "activity",
    "xprompts",
    "plans_questions",
)
VIEW_LABELS: dict[StatisticsView, str] = {
    "overview": "Overview",
    "runs": "Runs",
    "runners": "Runners",
    "projects": "Projects",
    "providers": "Providers",
    "runtime": "Runtime",
    "activity": "Activity",
    "xprompts": "XPrompts",
    "plans_questions": "Plans & Questions",
}
VIEW_COMPACT_LABELS: dict[StatisticsView, str] = {
    **VIEW_LABELS,
    "plans_questions": "Plans/Q",
}
VIEW_DESCRIPTIONS: dict[StatisticsView, str] = {
    "overview": "Totals and trends across runs, commits, plans, and questions.",
    "runs": "Run outcomes, retries, workspace usage, and activity over time.",
    "runners": "Runner occupancy, concurrency trends, and current-limit context.",
    "projects": "Run, ChangeSpec, commit, and runtime activity by project.",
    "providers": "Provider, model, and effort usage with success and runtime measures.",
    "runtime": "Runtime distribution and share grouped by the selected dimension.",
    "activity": "Skill and memory usage across agents in the selected scope.",
    "xprompts": (
        "XPrompt usage across prompts, with model, project, and co-usage breakdowns."
    ),
    "plans_questions": "Plan decisions, epic structure, and agent question patterns.",
}

PROJECTS_GROUP_ORDER: tuple[ProjectsGroupBy, ...] = (
    "project",
    "changespec",
    "drilldown",
)
XPROMPTS_GROUP_ORDER: tuple[XPromptsGroupBy, ...] = (
    "usage",
    "model",
    "project",
    "pairing",
)

RUNTIME_GROUP_ORDER: tuple[RuntimeGroupBy, ...] = (
    "tribe",
    "clan",
    "family",
    "agent",
    "provider",
    "model",
    "workflow",
    "project",
    "changespec",
)


def statistics_view_supports_grouping(view: StatisticsView) -> bool:
    """Return whether ``view`` exposes a configurable grouping strategy."""
    return view in ("projects", "runtime", "xprompts")


@dataclass(frozen=True, slots=True)
class StatisticsViewData:
    """One immutable result painted by :class:`StatisticsPane`."""

    view: StatisticsView
    selected_range: StatsRange
    runtime_group_by: RuntimeGroupBy
    generated_at: float
    views: StatisticsViews
    project_filter: str | None = None
    xprompt_focus: str | None = None
    project_display_snapshot: ProjectDisplaySnapshot = field(
        default_factory=ProjectDisplaySnapshot
    )


def load_statistics_view(
    view: StatisticsView,
    selected_range: StatsRange,
    runtime_group_by: RuntimeGroupBy,
    project_filter: str | None = None,
    xprompt_focus: str | None = None,
) -> StatisticsViewData:
    """Query composite bindings and build all view models off-thread."""
    from sase.config.core import get_max_running_agents

    project_display_snapshot = load_project_display_snapshot()
    current_runner_limit = get_max_running_agents()
    run_payload = query_run_stats(
        start_ts=selected_range.start_ts,
        end_ts=selected_range.end_ts,
        runtime_group_by=runtime_group_by,
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
            runtime_group_by=runtime_group_by,
            top_n=1,
            project=project_filter,
        )
    return StatisticsViewData(
        view=view,
        selected_range=selected_range,
        runtime_group_by=runtime_group_by,
        generated_at=time.time(),
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
    )


__all__ = [
    "PROJECTS_GROUP_ORDER",
    "RUNTIME_GROUP_ORDER",
    "XPROMPTS_GROUP_ORDER",
    "VIEW_DESCRIPTIONS",
    "VIEW_COMPACT_LABELS",
    "VIEW_LABELS",
    "VIEW_ORDER",
    "StatisticsView",
    "StatisticsViewData",
    "ProjectsGroupBy",
    "XPromptsGroupBy",
    "load_statistics_view",
    "statistics_view_supports_grouping",
]
