"""Wait projection for agent list entries."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.agent.running import RunningAgentInfo
from sase.core.agent_scan_wire import AgentMetaWire, WaitingMarkerWire
from sase.core.time import get_timezone

from ._agent_list_entry_models import AgentWaitInfo


def wait_info(
    agent: RunningAgentInfo,
    meta: AgentMetaWire | None,
    waiting: WaitingMarkerWire | None,
    now: datetime,
) -> AgentWaitInfo:
    wait_for = tuple(waiting.waiting_for) if waiting is not None else ()
    if not wait_for and meta is not None:
        wait_for = tuple(meta.wait_for)
    wait_for_beads = tuple(waiting.wait_for_beads) if waiting is not None else ()
    if not wait_for_beads and meta is not None:
        wait_for_beads = tuple(meta.wait_for_beads)
    wait_for_hoods = tuple(waiting.wait_for_hoods) if waiting is not None else ()
    if not wait_for_hoods and meta is not None:
        wait_for_hoods = tuple(meta.wait_for_hoods)
    wait_duration = (
        waiting.wait_duration
        if waiting is not None and waiting.wait_duration is not None
        else meta.wait_duration
        if meta is not None
        else None
    )
    wait_until = (
        waiting.wait_until
        if waiting is not None and waiting.wait_until
        else meta.wait_until
        if meta is not None
        else None
    )
    queue_weight = meta.queue_weight if meta is not None else None
    queue_weight_explicit = meta.queue_weight_explicit if meta is not None else False
    queue_weight_invalid = meta.queue_weight_invalid if meta is not None else False
    queue_weight_error = meta.queue_weight_error if meta is not None else None
    if waiting is not None and (
        waiting.queue_weight is not None or waiting.queue_weight_invalid
    ):
        queue_weight = waiting.queue_weight
        queue_weight_explicit = waiting.queue_weight_explicit
        queue_weight_invalid = waiting.queue_weight_invalid
        queue_weight_error = waiting.queue_weight_error
    queue_capacity = (
        waiting.queue_capacity
        if waiting is not None and waiting.queue_capacity is not None
        else meta.queue_capacity
        if meta is not None
        else None
    )
    queue_capacity_explicit = (
        waiting.queue_capacity_explicit
        if waiting is not None
        else meta.queue_capacity_explicit
        if meta is not None
        else False
    )
    if queue_capacity is None:
        fallback_capacity = (
            waiting.wait_runners
            if waiting is not None
            else meta.wait_runners
            if meta is not None
            else None
        )
        if fallback_capacity is not None:
            queue_capacity = fallback_capacity
            queue_capacity_explicit = (
                waiting.wait_runners_explicit
                if waiting is not None
                else meta.wait_runners_explicit
                if meta is not None
                else False
            )
    queue_capacity_multiplier = None
    if queue_capacity is None:
        if waiting is not None and waiting.queue_capacity_multiplier is not None:
            queue_capacity_multiplier = waiting.queue_capacity_multiplier
        elif meta is not None:
            queue_capacity_multiplier = meta.queue_capacity_multiplier
    return AgentWaitInfo(
        wait_for=wait_for,
        wait_for_beads=wait_for_beads,
        wait_for_hoods=wait_for_hoods,
        wait_for_epics_of=_wait_for_epics_of(waiting, meta),
        epic_follows=_epic_follows(waiting, meta),
        wait_duration_seconds=wait_duration,
        wait_until=wait_until,
        remaining_seconds=_remaining_wait_seconds(
            agent, wait_duration, wait_until, now
        ),
        queue_capacity=queue_capacity,
        queue_capacity_explicit=queue_capacity_explicit,
        queue_capacity_multiplier=queue_capacity_multiplier,
        wait_runners=queue_capacity,
        wait_runners_explicit=queue_capacity_explicit,
        wait_priority=(
            waiting.wait_priority
            if waiting is not None
            else meta.wait_priority
            if meta is not None
            else None
        ),
        queue_weight=queue_weight,
        queue_weight_explicit=queue_weight_explicit,
        queue_weight_invalid=queue_weight_invalid,
        queue_weight_error=queue_weight_error,
        slot_requested_at=(waiting.slot_requested_at if waiting is not None else None),
        held_by=(waiting.held_by if waiting is not None else None),
        hold_expires_at=(waiting.hold_expires_at if waiting is not None else None),
    )


def _wait_for_epics_of(
    waiting: WaitingMarkerWire | None,
    meta: AgentMetaWire | None,
) -> tuple[str, ...]:
    """Return armed follow targets, preferring the waiting marker."""
    if waiting is not None and waiting.wait_for_epics_of:
        return tuple(waiting.wait_for_epics_of)
    if meta is not None and meta.wait_for_epics_of:
        return tuple(meta.wait_for_epics_of)
    return ()


def _epic_follows(
    waiting: WaitingMarkerWire | None,
    meta: AgentMetaWire | None,
) -> tuple[dict[str, object], ...]:
    """Return persisted follow stages as JSON-serializable dicts."""
    raw: object = None
    if waiting is not None and waiting.wait_epic_follows:
        raw = waiting.wait_epic_follows
    elif meta is not None and meta.wait_epic_follows:
        raw = meta.wait_epic_follows
    if not isinstance(raw, (list, tuple)):
        return ()
    try:
        from sase.core.wait_epic_follow_view import epic_follow_views
    except ImportError:  # pragma: no cover - core always present in sase.
        return ()
    try:
        views = epic_follow_views(raw)
    except Exception:  # noqa: BLE001 - projection never fails the list.
        return ()
    return tuple(
        {
            "target": view.target,
            "state": view.state,
            "epic_ids": list(view.epic_ids),
            "added_bead_ids": list(view.added_bead_ids),
            "members": list(view.members),
            "since": view.since,
            "reason": view.reason,
            "detail": view.detail,
            "resume_command": view.resume_command,
            "skipped_epic_ids": list(view.skipped_epic_ids),
        }
        for view in views
    )


def _remaining_wait_seconds(
    agent: RunningAgentInfo,
    wait_duration: float | None,
    wait_until: str | None,
    now: datetime,
) -> int | None:
    target = _parse_iso_datetime(wait_until)
    if target is None and wait_duration is not None and agent.started_at is not None:
        target = agent.started_at.astimezone(get_timezone()) + _seconds_delta(
            wait_duration
        )
    if target is None:
        return None
    remaining = int((target - now.astimezone(get_timezone())).total_seconds())
    return max(remaining, 0)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=get_timezone())
    return parsed.astimezone(get_timezone())


def _seconds_delta(seconds: float) -> timedelta:
    return timedelta(seconds=max(float(seconds), 0.0))
