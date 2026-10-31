"""Parsing, formatting, and validation for wait modal field values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sase.ace.tui.models.agent_time import format_compact_duration, format_wait_until
from sase.core.time import local_now
from sase.macro._directive_time import parse_absolute_time, parse_duration
from sase.macro._exceptions import DirectiveError


@dataclass(frozen=True)
class TimeValidation:
    valid: bool
    token: str | None
    message: str
    css_class: str


@dataclass(frozen=True)
class CapacityValidation:
    valid: bool
    value: int | None
    message: str
    css_class: str
    multiplier: float | None = None


@dataclass(frozen=True)
class PriorityValidation:
    valid: bool
    value: int | None
    message: str
    css_class: str


def parse_agents_value(value: str) -> list[str]:
    """Parse comma-separated wait targets, including ``turn=<agent>`` names.

    Unknown ``key=`` fragments and incomplete ``turn=`` values are skipped
    so live typing does not fail the follow-epics preview.
    """
    session, turn_agents = parse_agents_field_lenient(value)
    merged = list(session)
    merged.extend(name for name in turn_agents if name not in session)
    return merged


def parse_agents_field(value: str) -> tuple[list[str], list[str]]:
    """Parse the Agents field into ``(session_agents, turn_agents)``.

    Empty comma entries are skipped. ``turn=<agent>`` is accepted. Other
    ``key=`` forms raise :class:`sase.wait_spec.WaitSpecError`. An empty
    field yields two empty lists.
    """
    from sase.wait_spec import WaitSpecError, parse_wait_spec

    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        return [], []
    spec = parse_wait_spec(",".join(parts))
    if spec.beads or spec.hoods:
        raise WaitSpecError(
            "Agents field does not accept bead= or hood= "
            "(only agent names and turn=<agent> are allowed)"
        )
    turn_agents = list(spec.turn_target_agents)
    turn_set = set(turn_agents)
    session = [name for name in spec.agents if name not in turn_set]
    return session, turn_agents


def parse_agents_field_lenient(value: str) -> tuple[list[str], list[str]]:
    """Parse Agents live, skipping unknown or incomplete keyed fragments."""
    session: list[str] = []
    turn_agents: list[str] = []
    seen_session: set[str] = set()
    seen_turn: set[str] = set()
    for raw in value.split(","):
        entry = raw.strip()
        if not entry:
            continue
        if "=" in entry:
            key, _, rest = entry.partition("=")
            if key != "turn":
                continue
            name = rest.strip()
            if not name or any(ch.isspace() for ch in name):
                continue
            if name not in seen_turn:
                seen_turn.add(name)
                turn_agents.append(name)
            continue
        if entry not in seen_session:
            seen_session.add(entry)
            session.append(entry)
    return session, turn_agents


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


def prefill_capacity_token(
    capacity: int | None,
    multiplier: float | None = None,
) -> str:
    """Return a modal capacity-field prefill preserving the authored form."""
    if multiplier is not None:
        from sase.macro.queue_directive import format_queue_capacity_multiplier

        formatted = format_queue_capacity_multiplier(multiplier)
        return formatted if formatted is not None else ""
    if capacity is not None:
        return str(capacity)
    return ""


def validate_capacity_token(token: str) -> CapacityValidation:
    """Validate a runner-capacity budget for live preview."""
    token = token.strip()
    if not token:
        return CapacityValidation(
            valid=True,
            value=None,
            message="uses the global max_running_agents budget",
            css_class="wait-time-neutral",
        )
    from sase.macro.queue_directive import parse_queue_capacity_value

    try:
        parsed = parse_queue_capacity_value(token)
    except ValueError as exc:
        return CapacityValidation(
            valid=False,
            value=None,
            message=str(exc),
            css_class="wait-time-error",
        )
    if not isinstance(parsed, dict):
        return CapacityValidation(
            valid=False,
            value=None,
            message="capacity must be a positive integer or <M>x multiplier",
            css_class="wait-time-error",
        )
    multiplier = parsed.get("queue_capacity_multiplier")
    if multiplier is not None:
        from sase.macro.queue_directive import format_queue_capacity_multiplier

        try:
            numeric = float(str(multiplier))
        except (TypeError, ValueError):
            return CapacityValidation(
                valid=False,
                value=None,
                message="capacity must be a positive integer or <M>x multiplier",
                css_class="wait-time-error",
            )
        formatted = format_queue_capacity_multiplier(numeric)
        if formatted is None:
            return CapacityValidation(
                valid=False,
                value=None,
                message="capacity must be a positive integer or <M>x multiplier",
                css_class="wait-time-error",
            )
        return CapacityValidation(
            valid=True,
            value=None,
            message=f"uses a per-launch capacity budget of {formatted}",
            css_class="wait-time-valid",
            multiplier=numeric,
        )
    value = parsed.get("queue_capacity", parsed.get("capacity"))
    if value is None:
        return CapacityValidation(
            valid=False,
            value=None,
            message="capacity must be a positive integer or <M>x multiplier",
            css_class="wait-time-error",
        )
    try:
        capacity = int(value)
    except (TypeError, ValueError):
        return CapacityValidation(
            valid=False,
            value=None,
            message="capacity must be a positive integer or <M>x multiplier",
            css_class="wait-time-error",
        )
    if capacity < 1:
        from sase.macro.queue_directive import validate_queue_capacity

        try:
            validate_queue_capacity(token)
        except ValueError as exc:
            message = str(exc)
        else:
            message = "capacity must be at least 1"
        return CapacityValidation(
            valid=False,
            value=None,
            message=message,
            css_class="wait-time-error",
        )
    message = f"uses a per-launch capacity budget of {capacity}"
    if capacity == 1:
        message = "run alone: starts when one capacity unit is available"
    return CapacityValidation(
        valid=True,
        value=capacity,
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
