"""Agent runtime formatting helpers for run-agent completion notifications."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_time import format_compact_duration
from sase.core.time import get_timezone


def format_agent_run_runtime(
    *,
    launch_timestamp_suffix: str | None,
    run_started_at: str | None,
    completion_time: datetime,
) -> str | None:
    """Return the compact runtime for a terminal agent run.

    This mirrors the Agents-tab terminal leaf calculation: prefer the
    persisted execution-loop start time, and only fall back to the launch
    timestamp for historical rows that have no ``run_started_at``.
    """
    if run_started_at:
        start = _parse_iso_datetime(run_started_at)
        if start is None:
            return None
    else:
        start = _parse_launch_timestamp(launch_timestamp_suffix)
        if start is None:
            return None

    end = _normalize_for_delta(completion_time, start)
    return format_compact_duration((end - start).total_seconds())


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=get_timezone())
    return parsed


def _parse_launch_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    formats = (("%Y%m%d%H%M%S", 14), ("%y%m%d_%H%M%S", 13))
    for fmt, width in formats:
        candidate = raw[:width]
        try:
            parsed = datetime.strptime(candidate, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=get_timezone())
    return None


def _normalize_for_delta(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is None:
        return value.replace(tzinfo=None)
    return value
