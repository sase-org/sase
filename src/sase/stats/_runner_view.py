"""Builder for the Statistics runner-occupancy view."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import tzinfo

from sase.stats._view_models import (
    RunnerOccupancyRow,
    RunnersView,
    RunnerTrendSlice,
)
from sase.stats._view_payload import (
    Payload,
    integer,
    number,
    rows,
    slice_label,
)


def build_runners_view(
    run_payload: Payload,
    *,
    current_runner_limit: int | None,
    timezone: tzinfo,
) -> RunnersView:
    runners = run_payload.get("runners")
    if not isinstance(runners, Mapping):
        # Absent only for an all-time window with no recorded runner coverage
        # or an older/partial payload; render an unavailable, still-typed view.
        return RunnersView(
            available=False,
            start_ts=0.0,
            end_ts=0.0,
            peak_runners=0,
            peak_seconds=0.0,
            average_runners=0.0,
            busy_seconds=0.0,
            busy_share=0.0,
            runner_seconds=0.0,
            current_limit=current_runner_limit,
            distribution=(),
            trend=(),
            malformed_rows_skipped=0,
            invalid_intervals_skipped=0,
        )
    distribution = tuple(
        RunnerOccupancyRow(
            runners=integer(row.get("runners")),
            seconds=number(row.get("seconds")),
            share=number(row.get("share")),
        )
        for row in rows(runners, "distribution")
    )
    trend = tuple(
        RunnerTrendSlice(
            start_ts=number(row.get("start_ts")),
            end_ts=number(row.get("end_ts")),
            label=slice_label(
                number(row.get("start_ts")),
                number(row.get("end_ts")),
                timezone,
            ),
            average_runners=number(row.get("average_runners")),
            peak_runners=integer(row.get("peak_runners")),
            busy_seconds=number(row.get("busy_seconds")),
            runner_seconds=number(row.get("runner_seconds")),
        )
        for row in rows(runners, "trend")
    )
    return RunnersView(
        available=True,
        start_ts=number(runners.get("start_ts")),
        end_ts=number(runners.get("end_ts")),
        peak_runners=integer(runners.get("peak_runners")),
        peak_seconds=number(runners.get("peak_seconds")),
        average_runners=number(runners.get("average_runners")),
        busy_seconds=number(runners.get("busy_seconds")),
        busy_share=number(runners.get("busy_share")),
        runner_seconds=number(runners.get("runner_seconds")),
        current_limit=current_runner_limit,
        distribution=distribution,
        trend=trend,
        malformed_rows_skipped=integer(runners.get("malformed_rows_skipped")),
        invalid_intervals_skipped=integer(runners.get("invalid_intervals_skipped")),
    )
