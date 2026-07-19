"""Off-thread query and model building for the Admin Center Statistics pane."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from sase.stats.query import RuntimeGroupBy, query_activity_stats, query_run_stats
from sase.stats.ranges import StatsRange
from sase.stats.views import StatisticsViews, build_statistics_views

StatisticsView = Literal[
    "overview",
    "runs",
    "providers",
    "runtime",
    "activity",
    "plans_questions",
]

VIEW_ORDER: tuple[StatisticsView, ...] = (
    "overview",
    "runs",
    "providers",
    "runtime",
    "activity",
    "plans_questions",
)
VIEW_LABELS: dict[StatisticsView, str] = {
    "overview": "Overview",
    "runs": "Runs",
    "providers": "Providers",
    "runtime": "Runtime",
    "activity": "Activity",
    "plans_questions": "Plans & Questions",
}

RUNTIME_GROUP_ORDER: tuple[RuntimeGroupBy, ...] = (
    "tribe",
    "clan",
    "family",
    "agent",
    "provider",
    "model",
    "workflow",
)


@dataclass(frozen=True, slots=True)
class StatisticsViewData:
    """One immutable result painted by :class:`StatisticsPane`."""

    view: StatisticsView
    selected_range: StatsRange
    runtime_group_by: RuntimeGroupBy
    generated_at: float
    views: StatisticsViews


def load_statistics_view(
    view: StatisticsView,
    selected_range: StatsRange,
    runtime_group_by: RuntimeGroupBy,
) -> StatisticsViewData:
    """Query composite bindings and build all six view models off-thread."""
    run_payload = query_run_stats(
        start_ts=selected_range.start_ts,
        end_ts=selected_range.end_ts,
        runtime_group_by=runtime_group_by,
    )
    activity_payload = query_activity_stats(
        start_ts=selected_range.start_ts,
        end_ts=selected_range.end_ts,
    )
    previous_run_payload = None
    if selected_range.start_ts > 0:
        window_seconds = selected_range.end_ts - selected_range.start_ts
        previous_run_payload = query_run_stats(
            start_ts=selected_range.start_ts - window_seconds,
            end_ts=selected_range.start_ts,
            runtime_group_by=runtime_group_by,
            top_n=1,
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
        ),
    )


__all__ = [
    "RUNTIME_GROUP_ORDER",
    "VIEW_LABELS",
    "VIEW_ORDER",
    "StatisticsView",
    "StatisticsViewData",
    "load_statistics_view",
]
