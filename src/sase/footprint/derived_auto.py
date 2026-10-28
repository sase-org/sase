"""AXE telemetry as Footprint ``derived.auto`` rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from sase.core.time import get_timezone, local_now
from sase.footprint.derived_rows import coverage_row, daily_row, local_day
from sase.footprint.ids import sanitize

ORIGIN = "derived.auto"
_SURFACE = "auto"
_ACTOR = "automation"
_VIA = "auto"
_METRIC = "sase_axe_cycles_total"
_STEP_SECONDS = 86_400


def extract_auto_rows(
    *,
    catalog_ids: set[str],
    today: str,
    retention_days: int = 400,
    query: Callable[..., Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(days, rows, coverage)`` from AXE cycle telemetry.

    ``cycle_type`` maps onto ``auto:axe.<routine>`` when that ID is in the
    catalog. Unmapped labels, including every job without a matching series,
    are left unmeasured. Nothing is guessed.
    """
    payload = _load_payload(query, retention_days, now)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for series in payload.get("series", []):
        if not isinstance(series, Mapping):
            continue
        labels = series.get("labels")
        cycle_type = labels.get("cycle_type") if isinstance(labels, Mapping) else None
        if not isinstance(cycle_type, str) or not cycle_type.strip():
            continue
        feature_id = f"auto:axe.{sanitize(cycle_type)}"
        if feature_id not in catalog_ids:
            continue
        for point in series.get("points", []):
            if not isinstance(point, Mapping):
                continue
            day = local_day(point.get("ts"))
            if day is None:
                continue
            value = point.get("value", 0)
            n = int(value) if isinstance(value, int | float) else 0
            if n > 0:
                counts[(day, feature_id)] += n

    rows = [
        daily_row(day, feature_id, actor=_ACTOR, via=_VIA, n=n)
        for (day, feature_id), n in sorted(counts.items())
    ]
    days = sorted({day for day, _feature in counts} | {today})
    coverage = [
        coverage_row(
            day,
            _SURFACE,
            records=sum(
                n for (row_day, _feature), n in counts.items() if row_day == day
            ),
            human_active=0,
        )
        for day in days
    ]
    return days, rows, coverage


def _load_payload(
    query: Callable[..., Mapping[str, Any]] | None,
    retention_days: int,
    now: datetime | None,
) -> Mapping[str, Any]:
    end_ts = _unix_now(now)
    start_ts = end_ts - max(retention_days, 1) * _STEP_SECONDS
    if query is not None:
        return query(
            _METRIC,
            start_ts=start_ts,
            end_ts=end_ts,
            step_seconds=_STEP_SECONDS,
            group_by=["cycle_type"],
            aggregation="sum",
        )
    from sase.telemetry.query import query_range

    return query_range(
        _METRIC,
        start_ts=start_ts,
        end_ts=end_ts,
        step_seconds=_STEP_SECONDS,
        group_by=["cycle_type"],
        aggregation="sum",
    )


def _unix_now(now: datetime | None) -> int:
    current = now or local_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=get_timezone())
    return int(current.timestamp())


__all__ = ["ORIGIN", "extract_auto_rows"]
