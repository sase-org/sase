"""Slow Agents-load evidence for ``tui_freeze_report``.

Reads ``tui_agent_loads.jsonl`` rows (plus the ``.1`` rotation, loaded by the
caller) and summarizes slow *full* loads per instance and window: rate, the
``index`` sub-stage duration buckets, fallback-field counts, and top
``source`` values. Rows that predate ``artifact_source`` / ``repair_reason``
land in ``unrecorded``.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any


SLOW_LOAD_EVENT = "tui_agent_load_slow"
FULL_LOAD_KIND = "full"
UNRECORDED = "unrecorded"
TOP_SOURCES_LIMIT = 5
INDEX_BUCKET_ORDER = ("<1s", "1-5s", "5-15s", "15-30s", ">=30s", UNRECORDED)


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _row_ts(row: dict) -> float | None:
    """Return the row's epoch seconds from ``ts`` or ISO ``timestamp``."""
    ts = row.get("ts")
    if isinstance(ts, bool):
        pass
    elif isinstance(ts, (int, float)):
        return float(ts)
    timestamp = row.get("timestamp")
    if isinstance(timestamp, bool):
        return None
    if isinstance(timestamp, (int, float)):
        return float(timestamp)
    if isinstance(timestamp, str):
        try:
            parsed = datetime.fromisoformat(timestamp)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return None


def _is_full_slow_load(row: dict) -> bool:
    """Return whether *row* is a slow full Agents load.

    Legacy slow-load rows omit ``load_kind``; those still count as full.
    Explicit non-full kinds (``artifact_delta``, ``monitor_reconcile``) do not.
    """
    if row.get("event") != SLOW_LOAD_EVENT:
        return False
    kind = row.get("load_kind")
    if kind is None:
        return True
    if isinstance(kind, str) and not kind.strip():
        return True
    return kind == FULL_LOAD_KIND


def _field_label(value: object) -> str:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else UNRECORDED
    return UNRECORDED


def _index_bucket(seconds: object) -> str:
    if not _is_number(seconds) or float(seconds) < 0.0:
        return UNRECORDED
    value = float(seconds)
    if value < 1.0:
        return "<1s"
    if value < 5.0:
        return "1-5s"
    if value < 15.0:
        return "5-15s"
    if value < 30.0:
        return "15-30s"
    return ">=30s"


def _index_seconds(row: dict) -> object:
    substages = row.get("disk_substages")
    if not isinstance(substages, dict):
        return None
    return substages.get("index")


def _count_map(values: list[str]) -> dict[str, int]:
    counts = Counter(values)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def empty_slow_agent_loads(*, window_s: float = 0.0) -> dict[str, Any]:
    """Return a zeroed slow-load summary for an instance with no rows."""
    return {
        "slow_full_load_count": 0,
        "slow_full_loads_per_hour": 0.0,
        "window_s": round(max(0.0, window_s), 3),
        "index_stage_buckets": {name: 0 for name in INDEX_BUCKET_ORDER},
        "artifact_source": {},
        "repair_reason": {},
        "sources": {},
    }


def summarize_slow_agent_loads(
    rows: list[dict],
    *,
    since: float | None = None,
    until: float | None = None,
) -> dict[str, Any]:
    """Summarize slow full Agents loads for one instance bucket."""
    ordered = sorted(
        (row for row in rows if _row_ts(row) is not None),
        key=lambda row: _row_ts(row) or 0.0,
    )
    if since is None:
        since = (_row_ts(ordered[0]) or 0.0) if ordered else 0.0
    if until is None:
        until = (_row_ts(ordered[-1]) or since) if ordered else since
    window_s = max(0.0, until - since)
    windowed = [
        row for row in ordered if since <= (_row_ts(row) or 0.0) <= until
    ]
    full_loads = [row for row in windowed if _is_full_slow_load(row)]
    count = len(full_loads)
    per_hour = (count * 3600.0 / window_s) if window_s > 0 else 0.0
    buckets = {name: 0 for name in INDEX_BUCKET_ORDER}
    for row in full_loads:
        buckets[_index_bucket(_index_seconds(row))] += 1
    return {
        "slow_full_load_count": count,
        "slow_full_loads_per_hour": round(per_hour, 3),
        "window_s": round(window_s, 3),
        "index_stage_buckets": buckets,
        "artifact_source": _count_map(
            [_field_label(row.get("artifact_source")) for row in full_loads]
        ),
        "repair_reason": _count_map(
            [_field_label(row.get("repair_reason")) for row in full_loads]
        ),
        "sources": _count_map([_field_label(row.get("source")) for row in full_loads]),
    }


def format_slow_agent_loads(summary: dict[str, Any]) -> str:
    """Render one instance's slow-load section as indented text."""
    buckets = summary.get("index_stage_buckets") or {}
    bucket_bits = [
        f"{name} {int(buckets.get(name) or 0)}" for name in INDEX_BUCKET_ORDER
    ]
    source_items = list((summary.get("sources") or {}).items())[:TOP_SOURCES_LIMIT]
    source_bits = [f"{name} {count}" for name, count in source_items] or ["none"]
    artifact_items = list((summary.get("artifact_source") or {}).items())
    artifact_bits = [f"{name} {count}" for name, count in artifact_items] or [
        "none"
    ]
    repair_items = list((summary.get("repair_reason") or {}).items())
    repair_bits = [f"{name} {count}" for name, count in repair_items] or ["none"]
    lines = [
        (
            f"  slow agent loads: {summary.get('slow_full_load_count', 0)} full "
            f"({summary.get('slow_full_loads_per_hour', 0.0):.2f}/h)"
        ),
        "  index stage: " + "; ".join(bucket_bits),
        "  artifact_source: " + "; ".join(artifact_bits),
        "  repair_reason: " + "; ".join(repair_bits),
        "  top sources: " + "; ".join(source_bits),
    ]
    return "\n".join(lines)
