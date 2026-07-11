"""Selection and formatting helpers for slow tool calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sase.agent.status_buckets import agent_is_active
from sase.core.time import get_timezone

from ._constants import (
    DEFAULT_SLOW_TOOL_CALL_THRESHOLD_SECONDS,
    SLOW_TOOL_CALL_THRESHOLD_MS,
)
from ._entry import ToolCallEntry


@dataclass(frozen=True)
class SlowToolCall:
    """A tool-call entry paired with derived slow-call display state."""

    entry: ToolCallEntry
    started_at: datetime
    effective_duration_ms: int
    is_running: bool = False
    did_not_complete: bool = False


def format_long_duration(duration_ms: int) -> str:
    """Format a duration with minute promotion for slow-call surfaces."""
    duration_ms = max(0, int(duration_ms))
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    total_seconds = duration_ms // 1000
    if total_seconds < 60:
        return f"{total_seconds}s"
    total_minutes, seconds = divmod(total_seconds, 60)
    if total_minutes < 60:
        if seconds:
            return f"{total_minutes}m {seconds}s"
        return f"{total_minutes}m"
    hours, minutes = divmod(total_minutes, 60)
    if minutes:
        return f"{hours}h {minutes}m"
    return f"{hours}h"


def agent_is_active_for_slow_tool_calls(agent: object) -> bool:
    """Return whether the row's runtime can still complete pending calls."""
    status = getattr(agent, "status", None)
    return agent_is_active(status) or status == "WAITING"


def slow_tool_call_threshold_ms_from_config(
    config: Mapping[str, Any] | None,
) -> int:
    """Return ACE slow-tool threshold milliseconds from config-like data."""
    section = _tool_calls_config_section(config)
    value = section.get(
        "slow_threshold_seconds", DEFAULT_SLOW_TOOL_CALL_THRESHOLD_SECONDS
    )
    seconds = _coerce_non_negative_int(value)
    if seconds is None:
        seconds = DEFAULT_SLOW_TOOL_CALL_THRESHOLD_SECONDS
    return seconds * 1000


def normalize_slow_tool_call_threshold_ms(value: object) -> int:
    """Return a valid millisecond threshold, falling back to the default."""
    threshold_ms = _coerce_non_negative_int(value)
    if threshold_ms is None:
        return SLOW_TOOL_CALL_THRESHOLD_MS
    return threshold_ms


def _slow_tool_call_threshold_ms_from_app(app: object | None) -> int:
    """Return the cached ACE slow-tool threshold from an app-like object."""
    if app is None:
        return SLOW_TOOL_CALL_THRESHOLD_MS
    return normalize_slow_tool_call_threshold_ms(
        getattr(app, "_slow_tool_call_threshold_ms", SLOW_TOOL_CALL_THRESHOLD_MS)
    )


def slow_tool_call_threshold_ms_from_widget(widget: object) -> int:
    """Return the cached ACE slow-tool threshold for a widget-like object."""
    try:
        app = cast(Any, widget).app
    except Exception:
        return SLOW_TOOL_CALL_THRESHOLD_MS
    return _slow_tool_call_threshold_ms_from_app(app)


def select_slow_tool_calls(
    entries: tuple[ToolCallEntry, ...],
    *,
    now: datetime,
    agent_is_active: bool,
    agent_end_reference: datetime | None,
    threshold_ms: int = SLOW_TOOL_CALL_THRESHOLD_MS,
) -> tuple[SlowToolCall, ...]:
    """Return slow tool calls in ascending command start-time order."""
    threshold_ms = normalize_slow_tool_call_threshold_ms(threshold_ms)
    now_utc = _coerce_datetime(now)
    assert now_utc is not None
    end_reference_utc = _coerce_datetime(agent_end_reference)
    slow_calls: list[SlowToolCall] = []

    for entry in entries:
        if entry.status == "subagent" or entry.event in {
            "SubagentStart",
            "SubagentStop",
        }:
            continue

        start = _parse_timestamp(entry.recorded_at)
        if start is None:
            continue

        if entry.status == "incomplete":
            completed_duration_ms = _completed_duration_ms(entry, start)
            if completed_duration_ms is None:
                continue
            candidate = SlowToolCall(
                entry=entry,
                started_at=start,
                effective_duration_ms=completed_duration_ms,
                did_not_complete=True,
            )
        elif entry.status == "pending":
            if agent_is_active:
                duration_ms = _duration_ms(start, now_utc)
                candidate = SlowToolCall(
                    entry=entry,
                    started_at=start,
                    effective_duration_ms=duration_ms,
                    is_running=True,
                )
            elif end_reference_utc is not None:
                duration_ms = _duration_ms(start, end_reference_utc)
                candidate = SlowToolCall(
                    entry=entry,
                    started_at=start,
                    effective_duration_ms=duration_ms,
                    did_not_complete=True,
                )
            else:
                continue
        else:
            completed_duration_ms = _completed_duration_ms(entry, start)
            if completed_duration_ms is None:
                continue
            candidate = SlowToolCall(
                entry=entry,
                started_at=start,
                effective_duration_ms=completed_duration_ms,
            )

        if candidate.effective_duration_ms >= threshold_ms:
            slow_calls.append(candidate)

    return tuple(
        sorted(slow_calls, key=lambda item: (item.started_at, item.entry.line_number))
    )


def _tool_calls_config_section(config: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(config, Mapping):
        return {}
    ace_config = config.get("ace")
    if isinstance(ace_config, Mapping):
        config = ace_config
    tool_calls_config = config.get("tool_calls")
    if isinstance(tool_calls_config, Mapping):
        return tool_calls_config
    return config


def _coerce_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        candidate = value
    elif isinstance(value, float) and value.is_integer():
        candidate = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            candidate = int(stripped, 10)
        except ValueError:
            return None
    else:
        return None
    if candidate < 0:
        return None
    return candidate


def _completed_duration_ms(entry: ToolCallEntry, start: datetime) -> int | None:
    if entry.duration_ms is not None:
        return max(0, int(entry.duration_ms))
    completed_at = _parse_timestamp(entry.completed_at)
    if completed_at is None:
        return None
    return _duration_ms(start, completed_at)


def _duration_ms(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() * 1000))


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _coerce_datetime(parsed)


def _coerce_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=get_timezone())
    return value.astimezone(UTC)


__all__ = [
    "SlowToolCall",
    "agent_is_active_for_slow_tool_calls",
    "format_long_duration",
    "normalize_slow_tool_call_threshold_ms",
    "select_slow_tool_calls",
    "slow_tool_call_threshold_ms_from_config",
    "slow_tool_call_threshold_ms_from_widget",
]
