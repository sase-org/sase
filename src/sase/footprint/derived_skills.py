"""Skill-use log counts as Footprint ``derived.skills`` rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
import json
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.footprint.derived_rows import coverage_row, daily_row, local_day
from sase.footprint.ids import custom_id, sanitize

ORIGIN = "derived.skills"
_SURFACE = "skill"
_ACTOR = "agent"
_VIA = "prompt"


def extract_skill_rows(
    *,
    catalog_ids: set[str],
    today: str,
    projects_dir: Path | None = None,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(days, rows, coverage)`` from ``skill_uses.jsonl`` files.

    Only ``skill_name`` and ``timestamp`` are read. Every other field on the
    source log is ignored so identity never reaches a derived row.
    """
    root = Path(projects_dir) if projects_dir is not None else sase_projects_dir()
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for event in _iter_skill_events(root):
        name = event.get("skill_name")
        if not isinstance(name, str) or not name.strip():
            continue
        day = local_day(event.get("timestamp"))
        if day is None:
            continue
        counts[(day, _skill_id(name, catalog_ids))] += 1

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


def _iter_skill_events(projects_dir: Path) -> Iterable[Mapping[str, Any]]:
    if not projects_dir.is_dir():
        return
    for log_path in sorted(projects_dir.glob("*/skill_uses.jsonl")):
        try:
            text = log_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                yield data


def _skill_id(name: str, catalog_ids: set[str]) -> str:
    feature_id = f"skill:{sanitize(name)}"
    if feature_id in catalog_ids:
        return feature_id
    return custom_id("skill")


__all__ = ["ORIGIN", "extract_skill_rows"]
