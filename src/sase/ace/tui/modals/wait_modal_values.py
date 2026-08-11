"""Parsing, formatting, and validation for wait modal field values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sase.ace.tui.models.agent_time import format_compact_duration, format_wait_until
from sase.core.time import local_now
from sase.xprompt._directive_time import parse_absolute_time, parse_duration
from sase.xprompt._exceptions import DirectiveError


@dataclass(frozen=True)
class TimeValidation:
    valid: bool
    token: str | None
    message: str
    css_class: str


@dataclass(frozen=True)
class RunnersValidation:
    valid: bool
    value: int | None
    message: str
    css_class: str


@dataclass(frozen=True)
class PriorityValidation:
    valid: bool
    value: int | None
    message: str
    css_class: str


def parse_agents_value(value: str) -> list[str]:
    """Parse comma-separated wait targets."""
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_beads_value(value: str) -> list[str]:
    """Parse comma-separated bead wait targets, preserving order without duplicates."""
    return list(dict.fromkeys(parse_agents_value(value)))


def active_fragment(value: str) -> str:
    """Return the comma-separated fragment under completion."""
    return value.rsplit(",", 1)[-1].strip()


def replace_active_fragment(value: str, replacement: str) -> str:
    """Replace the current comma fragment with *replacement* and a trailing comma."""
    prefix, separator, _fragment = value.rpartition(",")
    if separator:
        return f"{prefix.strip()}, {replacement}, "
    return f"{replacement}, "


def _format_duration_token(seconds: float) -> str:
    """Render stored wait seconds as a compact directive token."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return "".join(parts)


def _format_wait_until_token(iso_value: str) -> str:
    """Render stored ISO wait target as a user-editable absolute-time token."""
    target = datetime.fromisoformat(iso_value)
    now = datetime.now(target.tzinfo) if target.tzinfo is not None else local_now()
    if target.date() == now.date():
        return target.strftime("%H%M")
    return target.strftime("%y%m%d/%H%M")


def prefill_time_token(
    wait_duration: float | None,
    wait_until: str | None,
) -> str:
    """Return a modal time-field prefill from stored wait fields."""
    if wait_duration is not None:
        return _format_duration_token(wait_duration)
    if wait_until:
        try:
            return _format_wait_until_token(wait_until)
        except ValueError:
            return ""
    return ""


def validate_time_token(token: str) -> TimeValidation:
    """Validate a duration or absolute wait-time token for live preview."""
    token = token.strip()
    if not token:
        return TimeValidation(
            valid=True,
            token=None,
            message="e.g. 5m | 1h30m | 1430 | 260415/0900",
            css_class="wait-time-neutral",
        )

    duration = parse_duration(token)
    if duration is not None:
        label = format_compact_duration(duration)
        return TimeValidation(
            valid=True,
            token=token,
            message=f"floor: waits {label} after deps",
            css_class="wait-time-valid",
        )

    try:
        absolute = parse_absolute_time(token)
    except DirectiveError as exc:
        return TimeValidation(
            valid=False,
            token=None,
            message=str(exc),
            css_class="wait-time-error",
        )
    if absolute is not None:
        return TimeValidation(
            valid=True,
            token=token,
            message=f"until {format_wait_until(absolute)}",
            css_class="wait-time-valid",
        )

    return TimeValidation(
        valid=False,
        token=None,
        message="time must be a duration or absolute time",
        css_class="wait-time-error",
    )


def validate_runners_token(token: str) -> RunnersValidation:
    """Validate an existing-runner threshold for live preview."""
    token = token.strip()
    if not token:
        return RunnersValidation(
            valid=True,
            value=None,
            message="uses the global max_running_agents cap",
            css_class="wait-time-neutral",
        )
    if not token.isdigit():
        return RunnersValidation(
            valid=False,
            value=None,
            message="runners must be a non-negative integer",
            css_class="wait-time-error",
        )
    value = int(token)
    message = f"starts when at most {value} other agents are running"
    if value == 0:
        message = "drain barrier: starts when no other agents are running"
    return RunnersValidation(
        valid=True,
        value=value,
        message=message,
        css_class="wait-time-valid",
    )


def validate_priority_token(token: str) -> PriorityValidation:
    """Validate a runner-slot priority for live preview."""
    token = token.strip()
    if not token:
        return PriorityValidation(
            valid=True,
            value=None,
            message="lower values start first; default is 10",
            css_class="wait-time-neutral",
        )
    if not token.isdigit():
        return PriorityValidation(
            valid=False,
            value=None,
            message="priority must be a non-negative integer",
            css_class="wait-time-error",
        )
    value = int(token)
    return PriorityValidation(
        valid=True,
        value=value,
        message=f"runner-slot priority {value}; lower values start first",
        css_class="wait-time-valid",
    )
