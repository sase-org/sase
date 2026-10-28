"""Macro launch history as Footprint ``derived.macros`` rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.footprint.derived_rows import coverage_row, daily_row, local_day
from sase.footprint.ids import custom_id, sanitize

ORIGIN = "derived.macros"
_SURFACE = "macro"
_VIA = "prompt"


def extract_macro_rows(
    *,
    catalog_ids: set[str],
    today: str,
    query: Callable[..., Mapping[str, Any]] | None = None,
    index_path: Path | str | None = None,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(days, rows, coverage)`` from launch-prompt macro data."""
    payload = _load_payload(query, index_path)
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for raw in payload.get("rows", []):
        if not isinstance(raw, Mapping):
            continue
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        day = local_day(raw.get("ts"))
        if day is None:
            continue
        feature_id = _macro_id(name, catalog_ids)
        actor = "agent" if bool(raw.get("has_parent")) else "human"
        n = raw.get("n", 1)
        counts[(day, feature_id, actor)] += int(n) if isinstance(n, int) else 1

    rows = [
        daily_row(day, feature_id, actor=actor, via=_VIA, n=n)
        for (day, feature_id, actor), n in sorted(counts.items())
    ]
    days = _coverage_days(counts, today)
    coverage = [
        coverage_row(
            day,
            _SURFACE,
            records=_day_records(counts, day),
            human_active=int(_day_has_actor(counts, day, "human")),
        )
        for day in days
    ]
    return days, rows, coverage


def _load_payload(
    query: Callable[..., Mapping[str, Any]] | None,
    index_path: Path | str | None,
) -> Mapping[str, Any]:
    if query is not None:
        return query(index_path=index_path) if index_path is not None else query()
    from sase.stats.query import query_macro_usage

    return query_macro_usage(index_path=index_path)


def _macro_id(name: str, catalog_ids: set[str]) -> str:
    feature_id = f"macro:{sanitize(name)}"
    if feature_id in catalog_ids:
        return feature_id
    return custom_id("macro")


def _coverage_days(counts: Mapping[tuple[str, str, str], int], today: str) -> list[str]:
    days = {day for day, _feature, _actor in counts}
    days.add(today)
    return sorted(days)


def _day_records(counts: Mapping[tuple[str, str, str], int], day: str) -> int:
    return sum(n for (row_day, _feature, _actor), n in counts.items() if row_day == day)


def _day_has_actor(
    counts: Mapping[tuple[str, str, str], int], day: str, actor: str
) -> bool:
    return any(
        row_day == day and row_actor == actor for row_day, _feature, row_actor in counts
    )


__all__ = ["ORIGIN", "extract_macro_rows"]
