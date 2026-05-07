"""Time/duration formatting helpers for the Agent model."""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent

_PLAN_RUNTIME_TERMINAL_STATUSES = {"DONE", "PLAN DONE"}
_ACTIVE_LEAF_STATUSES = {"RUNNING", "RETRYING"}


@dataclass(frozen=True)
class _RuntimeInterval:
    """Runtime interval data before display formatting."""

    elapsed_seconds: float
    terminal_time: datetime | None
    active: bool


def should_display_runtime_suffix(agent: "Agent") -> bool:
    """Return True when an Agents-tab row should show a runtime suffix."""
    if agent.parent_workflow is None:
        return True
    return agent.step_type == "agent"


def wait_until_target_and_reference(
    iso_str: str, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Return a wait target and timezone-compatible reference time."""
    target = datetime.fromisoformat(iso_str)
    if now is not None:
        reference = now
        if target.tzinfo is not None and reference.tzinfo is None:
            reference = reference.astimezone()
        elif target.tzinfo is None and reference.tzinfo is not None:
            target = target.replace(tzinfo=reference.tzinfo)
        return target, reference

    if target.tzinfo is not None:
        return target, datetime.now(target.tzinfo)
    return target, datetime.now()


def format_wait_until(iso_str: str) -> str:
    """Format an ISO 8601 target time for display.

    Same day: ``"14:30"`` (just the time).
    Different day: ``"Apr 11 14:30"`` (short month + day + time).
    """
    target, now = wait_until_target_and_reference(iso_str)
    if target.date() == now.date():
        return target.strftime("%H:%M")
    return target.strftime("%b %-d %H:%M")


def format_compact_duration(seconds: float) -> str:
    """Format seconds as a compact duration string (e.g., '4m32s', '1h5m').

    Shows the two most significant non-zero units:
    - >= 1h: 'Xh Ym'
    - >= 1m: 'Xm Ys'
    - < 1m: 'Xs'
    """
    total = max(0, int(seconds))
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}h{m:02d}m" if m else f"{h}h"
    if m > 0:
        return f"{m}m{s:02d}s" if s else f"{m}m"
    return f"{s}s"


def _format_finish_timestamp(
    stop: datetime, now: datetime | None = None
) -> tuple[str, str]:
    """Format a finish-time clock for the Agents-tab right-side suffix.

    Returns a ``(date_prefix, time)`` pair so the renderer can style the
    two halves differently:

    - Same calendar day: ``("", "HH:MM:SS")``.
    - Prior day, same year: ``("Mon DD ", "HH:MM")`` (trailing space owns
      the gap between the two halves).
    - Different year: ``("Mon DD 'YY", "")``.
    """
    reference = now if now is not None else datetime.now()
    if stop.date() == reference.date():
        return ("", stop.strftime("%H:%M:%S"))
    if stop.year == reference.year:
        return (stop.strftime("%b %-d "), stop.strftime("%H:%M"))
    return (stop.strftime("%b %-d '%y"), "")


def _row_runtime_terminal_time(agent: "Agent") -> datetime | None:
    """Return the terminal timestamp to anchor a completed row runtime."""
    if agent.stop_time is not None:
        return agent.stop_time
    if agent.status in _PLAN_RUNTIME_TERMINAL_STATUSES and agent.plan_times:
        return max(agent.plan_times)
    if agent.status == "PLANNING" and agent.plan_times:
        return max(agent.plan_times)
    if agent.status == "QUESTION" and agent.questions_times:
        return max(agent.questions_times)
    return None


def _leaf_runtime_interval(agent: "Agent", now: datetime) -> _RuntimeInterval | None:
    """Return the row's own runtime interval, excluding aggregate children."""
    if agent.start_time is None:
        return None

    effective_start = agent.run_start_time or agent.start_time
    terminal_time = _row_runtime_terminal_time(agent)
    if terminal_time is not None:
        return _RuntimeInterval(
            elapsed_seconds=(terminal_time - effective_start).total_seconds(),
            terminal_time=terminal_time,
            active=False,
        )

    if agent.status == "WAITING":
        if agent.run_start_time is None:
            return None
        return _RuntimeInterval(
            elapsed_seconds=(now - effective_start).total_seconds(),
            terminal_time=None,
            active=True,
        )

    if agent.status in _ACTIVE_LEAF_STATUSES:
        return _RuntimeInterval(
            elapsed_seconds=(now - effective_start).total_seconds(),
            terminal_time=None,
            active=True,
        )

    return None


def _aggregate_runtime(
    agent: "Agent", now: datetime, seen: set[int]
) -> _RuntimeInterval | None:
    """Return the aggregate interval from direct runtime children."""
    children = getattr(agent, "runtime_children", ())
    if not children:
        return None

    elapsed_seconds = 0.0
    active = False
    terminal_times: list[datetime] = []
    contributed = False
    for child in children:
        interval = _runtime_interval(child, now, seen)
        if interval is None:
            continue
        contributed = True
        elapsed_seconds += interval.elapsed_seconds
        active = active or interval.active
        if interval.terminal_time is not None:
            terminal_times.append(interval.terminal_time)

    if not contributed:
        return None
    return _RuntimeInterval(
        elapsed_seconds=elapsed_seconds,
        terminal_time=None if active else max(terminal_times, default=None),
        active=active,
    )


def _runtime_interval(
    agent: "Agent", now: datetime, seen: set[int] | None = None
) -> _RuntimeInterval | None:
    """Return aggregate runtime when available, otherwise leaf runtime."""
    if not should_display_runtime_suffix(agent):
        return None
    if seen is None:
        seen = set()
    agent_id = id(agent)
    if agent_id in seen:
        return None
    seen.add(agent_id)

    aggregate = _aggregate_runtime(agent, now, seen)
    if aggregate is not None:
        return aggregate
    return _leaf_runtime_interval(agent, now)


def compute_row_runtime(
    agent: "Agent",
    now: datetime | None = None,
) -> tuple[tuple[str, str] | None, str | None]:
    """Compute the right-side ``(timestamp, elapsed)`` suffix pair for a row.

    - ``(None, None)`` when no suffix should render (missing ``start_time``
      or pre-run ``WAITING`` with no ``run_start_time``).
    - Active rows: ``(None, "<dur>")``.
    - Finished rows: ``((date_prefix, time), "<dur>")`` where the
      ``(date_prefix, time)`` pair follows the tiers in
      :func:`_format_finish_timestamp`.

    Elapsed uses ``run_start_time`` when set so a long WAIT period doesn't
    inflate what reads as runtime; falls back to ``start_time``.
    """
    reference = now if now is not None else datetime.now()
    interval = _runtime_interval(agent, reference)
    if interval is None:
        return (None, None)
    if interval.terminal_time is not None:
        return (
            _format_finish_timestamp(interval.terminal_time, now=now),
            format_compact_duration(interval.elapsed_seconds),
        )
    return (None, format_compact_duration(interval.elapsed_seconds))


def runtime_suffix_ticks(agent: "Agent", _seen: set[int] | None = None) -> bool:
    """Return True when *agent* renders a runtime suffix that can tick."""
    if _seen is None:
        _seen = set()
    agent_id = id(agent)
    if agent_id in _seen:
        return False
    _seen.add(agent_id)

    if not should_display_runtime_suffix(agent):
        return False
    for child in getattr(agent, "runtime_children", ()):
        if runtime_suffix_ticks(child, _seen):
            return True
    if agent.stop_time is not None:
        return False
    if agent.status in _ACTIVE_LEAF_STATUSES:
        return agent.start_time is not None
    return agent.status == "WAITING" and agent.run_start_time is not None
