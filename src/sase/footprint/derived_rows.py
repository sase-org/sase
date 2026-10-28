"""Identity-free derived daily rows and coverage for Footprint extractors."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sase.core.time import parse_local
from sase.footprint.ids import is_valid_feature_id

DAILY_ROW_KEYS = frozenset(
    {
        "day",
        "feature_id",
        "actor",
        "via",
        "outcome",
        "n",
        "dur_ms_sum",
        "dur_ms_max",
    }
)
COVERAGE_ROW_KEYS = frozenset(
    {
        "day",
        "surface",
        "measured",
        "human_active",
        "records",
        "torn",
        "dropped",
        "unknown_ids",
        "incomplete",
    }
)

# Fields the privacy contract forbids on a derived row. Extractors may read
# source logs that contain these, but they must never copy them through.
FORBIDDEN_SOURCE_FIELDS = frozenset(
    {
        "agent_name",
        "artifacts_dir",
        "cwd",
        "host",
        "hostname",
        "path",
        "project",
        "prompt",
        "reason",
        "session",
        "username",
        "value",
    }
)


def local_day(value: str | int | float | datetime | None) -> str | None:
    """Return the configured-timezone calendar day for *value*, or ``None``."""
    parsed = parse_local(value)
    if parsed is None:
        return None
    return parsed.date().isoformat()


def daily_row(
    day: str,
    feature_id: str,
    *,
    actor: str,
    via: str,
    outcome: str = "ok",
    n: int = 1,
    dur_ms_sum: int = 0,
    dur_ms_max: int = 0,
) -> dict[str, Any]:
    """Return one derived daily aggregate row."""
    return {
        "day": day,
        "feature_id": feature_id,
        "actor": actor,
        "via": via,
        "outcome": outcome,
        "n": int(n),
        "dur_ms_sum": int(dur_ms_sum),
        "dur_ms_max": int(dur_ms_max),
    }


def coverage_row(
    day: str,
    surface: str,
    *,
    records: int,
    human_active: int,
    unknown_ids: int = 0,
    measured: int = 1,
) -> dict[str, Any]:
    """Return one derived coverage row for *surface* on *day*."""
    return {
        "day": day,
        "surface": surface,
        "measured": int(measured),
        "human_active": int(human_active),
        "records": int(records),
        "torn": 0,
        "dropped": 0,
        "unknown_ids": int(unknown_ids),
        "incomplete": 0,
    }


def assert_row_allowlist(rows: Iterable[Mapping[str, Any]]) -> None:
    """Raise if a derived row carries a key outside the daily allowlist."""
    for row in rows:
        extra = set(row) - DAILY_ROW_KEYS
        if extra:
            raise ValueError(f"derived row has forbidden keys: {sorted(extra)}")
        feature_id = str(row.get("feature_id", ""))
        if feature_id and not is_valid_feature_id(feature_id):
            raise ValueError(f"derived feature id {feature_id!r} is invalid")


__all__ = [
    "COVERAGE_ROW_KEYS",
    "DAILY_ROW_KEYS",
    "FORBIDDEN_SOURCE_FIELDS",
    "assert_row_allowlist",
    "coverage_row",
    "daily_row",
    "local_day",
]
