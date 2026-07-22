"""Safe conversions from loosely typed Statistics binding payloads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, tzinfo

from sase.stats._view_models import ActivityRow, CountRow, DistributionRow

Payload = Mapping[str, object]


def rows(payload: Payload, key: str) -> tuple[Payload, ...]:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def mapping(value: object) -> Payload:
    return value if isinstance(value, Mapping) else {}


def count_map(rows: tuple[Payload, ...]) -> dict[str, int]:
    return {text(row.get("name")): integer(row.get("count")) for row in rows}


def count_rows(rows: tuple[Payload, ...]) -> tuple[CountRow, ...]:
    return tuple(
        CountRow(text(row.get("name"), "unknown"), integer(row.get("count")))
        for row in rows
    )


def activity_rows(rows: tuple[Payload, ...]) -> tuple[ActivityRow, ...]:
    return tuple(
        ActivityRow(
            text(row.get("name"), "unknown"),
            integer(row.get("count")),
            integer(row.get("distinct_agents")),
        )
        for row in rows
    )


def distribution_rows(rows: tuple[Payload, ...]) -> tuple[DistributionRow, ...]:
    return tuple(
        DistributionRow(str(integer(row.get("value"))), integer(row.get("count")))
        for row in rows
    )


def integer(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    return int(value) if isinstance(value, (int, float)) else default


def boolean(value: object, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def number(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    return float(value) if isinstance(value, (int, float)) else default


def optional_number(value: object) -> float | None:
    return (
        number(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) and value else default


def ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def delta_ratio(current: int, previous: int | None) -> float | None:
    if previous is None:
        return None
    if previous == 0:
        return 0.0 if current == 0 else None
    return (current - previous) / previous


def bucket_label(start_ts: int, bucket_seconds: int, timezone: tzinfo) -> str:
    value = datetime.fromtimestamp(start_ts, timezone)
    return value.strftime("%a %H:%M" if bucket_seconds < 86_400 else "%b %d")


def slice_label(start_ts: float, end_ts: float, timezone: tzinfo) -> str:
    """Label a trend slice by its start in the configured SASE timezone.

    Sub-day slices carry a weekday and clock time; wider slices use a calendar
    date, mirroring :func:`bucket_label` so both charts read consistently.
    """
    value = datetime.fromtimestamp(start_ts, timezone)
    return value.strftime("%a %H:%M" if (end_ts - start_ts) < 86_400 else "%b %d")
