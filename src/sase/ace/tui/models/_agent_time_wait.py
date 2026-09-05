"""Wait-until, wait-countdown, and duration formatting helpers."""

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sase.core.time import get_timezone, local_now, parse_local, to_local

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent


def wait_until_target_and_reference(
    iso_str: str, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Return a wait target and timezone-compatible reference time."""
    target = datetime.fromisoformat(iso_str)
    if now is not None:
        reference = now
        if target.tzinfo is not None and reference.tzinfo is None:
            reference = reference.astimezone(get_timezone())
        elif target.tzinfo is None and reference.tzinfo is not None:
            target = target.replace(tzinfo=reference.tzinfo)
        return target, reference

    if target.tzinfo is not None:
        return target, datetime.now(target.tzinfo)
    return target, local_now()


def format_wait_until(iso_str: str, now: datetime | None = None) -> str:
    """Format an ISO 8601 target time for display.

    Same day: ``"14:30"`` (just the time).
    Different day: ``"Apr 11 14:30"`` (short month + day + time).
    """
    target, now = wait_until_target_and_reference(iso_str, now=now)
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


def queued_for_label(
    requested_at: str | None,
    now: datetime | None = None,
) -> str | None:
    """Return a compact elapsed label for a runner-slot request timestamp.

    ``requested_at`` is a stored ``slot_requested_at`` marker value. Both sides
    are normalized to the naive configured-tz arithmetic convention before
    subtracting, matching the rest of the TUI agent time model.
    """
    if not requested_at:
        return None
    parsed = parse_local(requested_at)
    if parsed is None:
        return None
    reference = local_now() if now is None else now
    elapsed = max(0.0, (to_local(reference) - to_local(parsed)).total_seconds())
    return format_compact_duration(elapsed)


def wait_display_agent(agent: "Agent") -> "Agent":
    """Return the row whose wait fields should drive display for *agent*."""
    return agent.wait_display_source or agent


def _reference_for_target(target: datetime, now: datetime | None) -> datetime:
    """Return a timezone-compatible reference time for *target*."""
    if now is not None:
        reference = now
    elif target.tzinfo is not None:
        reference = datetime.now(target.tzinfo)
    else:
        reference = local_now()

    if target.tzinfo is not None and reference.tzinfo is None:
        return reference.astimezone(get_timezone())
    if target.tzinfo is None and reference.tzinfo is not None:
        return reference.replace(tzinfo=None)
    return reference


def wait_remaining_seconds(agent: "Agent", now: datetime | None = None) -> float | None:
    """Return seconds left on an agent's wait time floor, if one is known."""
    wait_agent = wait_display_agent(agent)
    if wait_agent.wait_until:
        target, reference = wait_until_target_and_reference(
            wait_agent.wait_until,
            now=now,
        )
        return (target - reference).total_seconds()
    if wait_agent.wait_duration is None or wait_agent.start_time is None:
        return None
    if wait_agent.waiting_for or wait_agent.waiting_for_beads:
        return None
    target = wait_agent.start_time + timedelta(seconds=wait_agent.wait_duration)
    reference = _reference_for_target(target, now)
    return (target - reference).total_seconds()


def wait_countdown_ticks(agent: "Agent") -> bool:
    """Return True when a ``WAITING`` row has a time floor countdown."""
    if agent.status != "WAITING":
        return False
    wait_agent = wait_display_agent(agent)
    if wait_agent.wait_until:
        return True
    return (
        wait_agent.wait_duration is not None
        and wait_agent.start_time is not None
        and not wait_agent.waiting_for
        and not wait_agent.waiting_for_beads
    )
