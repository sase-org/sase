"""Time/duration formatting helpers for the Agent model."""

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent

_ACTIVE_PARENT_STATUSES = {
    "PLAN APPROVED",
    "EPIC APPROVED",
    "LEGEND APPROVED",
    "PLAN COMMITTED",
}


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
    if not should_display_runtime_suffix(agent):
        return (None, None)
    if agent.start_time is None:
        return (None, None)
    effective_start = agent.run_start_time or agent.start_time
    if agent.stop_time is not None:
        elapsed_secs = (agent.stop_time - effective_start).total_seconds()
        return (
            _format_finish_timestamp(agent.stop_time, now=now),
            format_compact_duration(elapsed_secs),
        )
    if agent.status == "WAITING" and agent.run_start_time is None:
        return (None, None)
    reference = now if now is not None else datetime.now()
    elapsed_secs = (reference - effective_start).total_seconds()
    return (None, format_compact_duration(elapsed_secs))


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
    if agent.start_time is None or agent.stop_time is not None:
        return False
    if agent.status in ("RUNNING", "RETRYING"):
        return True
    if agent.status == "WAITING" and agent.run_start_time is not None:
        return True
    if agent.status in _ACTIVE_PARENT_STATUSES:
        return True
    return any(
        runtime_suffix_ticks(followup, _seen)
        for followup in getattr(agent, "followup_agents", ())
    )
