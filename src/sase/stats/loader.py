"""Textual-free Statistics view loader shared by the TUI and later CLI."""

from __future__ import annotations

import time
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import Any

from sase.project_display_names import (
    ProjectDisplaySnapshot,
    load_project_display_snapshot,
)
from sase.core.time import get_timezone
from sase.stats import PerfView, build_perf_view
from sase.stats.perf_query import (
    PerfGroupBy,
    query_perf_logs,
    query_perf_telemetry,
)
from sase.stats.project import (
    ProjectStatsFacet,
    ProjectStatsQuery,
    ProjectStatsView,
    load_project_stats,
)
from sase.stats.query import RuntimeGroupBy, query_activity_stats, query_run_stats
from sase.stats.ranges import StatsRange
from sase.stats.registry import StatisticsView
from sase.stats.views import StatisticsViews, build_statistics_views
from sase.telemetry._config import HealthThresholds

_FIXED_RUNTIME_GROUP_BY: RuntimeGroupBy = "tribe"
_PRIMARY_PROJECT_FACETS: frozenset[ProjectStatsFacet] = frozenset({"output", "runs"})


@dataclass(frozen=True, slots=True)
class StatisticsViewData:
    """One immutable result painted by the Statistics pane."""

    view: StatisticsView
    selected_range: StatsRange
    generated_at: float
    views: StatisticsViews | None = None
    project_filter: str | None = None
    macro_focus: str | None = None
    project_display_snapshot: ProjectDisplaySnapshot = field(
        default_factory=ProjectDisplaySnapshot
    )
    perf: PerfView | None = None
    project_stats: ProjectStatsView | None = None
    footprint: dict[str, Any] | None = None
    footprint_lens: str = "map"
    footprint_actor: str = "you"
    footprint_area: str | None = None


def load_statistics_view(
    view: StatisticsView,
    selected_range: StatsRange,
    project_filter: str | None = None,
    macro_focus: str | None = None,
    perf_group_by: PerfGroupBy = "subsystem",
    *,
    facets: Collection[ProjectStatsFacet] | None = None,
    preset: str | None = None,
    footprint_lens: str = "map",
    footprint_actor: str = "you",
    footprint_area: str | None = None,
) -> StatisticsViewData:
    """Query composite bindings or the Projects report off-thread."""
    if view == "footprint":
        from sase.footprint.query import build_report_request, fetch_report

        duration_seconds = max(1, selected_range.end_ts - selected_range.start_ts)
        window_days = (
            None
            if selected_range.start_ts <= 0
            else max(1, math.ceil(duration_seconds / 86_400))
        )
        end_ts = max(0, selected_range.end_ts - 1)
        today = datetime.fromtimestamp(end_ts, tz=get_timezone()).date().isoformat()
        request = build_report_request(
            lens=footprint_lens,
            actor=footprint_actor,
            window_days=window_days,
            area=footprint_area,
            today=today,
        )
        return StatisticsViewData(
            view=view,
            selected_range=selected_range,
            generated_at=time.time(),
            project_filter=project_filter,
            macro_focus=macro_focus,
            footprint=fetch_report(request),
            footprint_lens=footprint_lens,
            footprint_actor=footprint_actor,
            footprint_area=footprint_area,
        )

    from sase.config.core import get_max_running_agents
    from sase.telemetry._config import get_telemetry_config as load_telemetry_config

    if view == "projects":
        return _load_projects_statistics_view(
            selected_range,
            project_filter,
            facets=(
                frozenset(facets) if facets is not None else _PRIMARY_PROJECT_FACETS
            ),
            preset=preset,
        )

    project_display_snapshot = load_project_display_snapshot()
    current_runner_limit = get_max_running_agents()
    run_payload = query_run_stats(
        start_ts=selected_range.start_ts,
        end_ts=selected_range.end_ts,
        runtime_group_by=_FIXED_RUNTIME_GROUP_BY,
        project=project_filter,
        macro_focus=macro_focus,
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
        macro_focus=macro_focus,
        project_display_snapshot=project_display_snapshot,
        perf=perf,
    )


def _project_stats_query(
    selected_range: StatsRange,
    project_filter: str | None = None,
    *,
    preset: str | None = None,
) -> ProjectStatsQuery:
    """Build the TUI/CLI-shared Projects query with fetch disabled."""
    return ProjectStatsQuery(
        range=selected_range,
        project_refs=(project_filter,) if project_filter else (),
        preset=preset,
        fetch=False,
    )


def _load_projects_statistics_view(
    selected_range: StatsRange,
    project_filter: str | None,
    *,
    facets: frozenset[ProjectStatsFacet],
    preset: str | None,
) -> StatisticsViewData:
    report = load_project_stats(
        _project_stats_query(selected_range, project_filter, preset=preset),
        facets=facets,
    )
    return StatisticsViewData(
        view="projects",
        selected_range=selected_range,
        generated_at=time.time(),
        views=None,
        project_filter=project_filter,
        project_display_snapshot=report.display_snapshot,
        project_stats=report,
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
    "StatisticsViewData",
    "load_statistics_view",
]
