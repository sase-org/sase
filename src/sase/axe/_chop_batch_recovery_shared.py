"""Shared data and notifications for chop batch recovery."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sase.core.time import get_timezone

from .chop_batch_store import (
    load_chop_batch_notice_state,
    pending_chop_batch_notices,
    update_chop_batch_notice_state,
)


@dataclass(frozen=True)
class ChopBatchRecoveryResult:
    """Outcome of attempting recovery for one stored batch."""

    routine: str
    job: str
    batch_id: str
    kind: str  # "ordinary", "typed", "skipped", "blocked", "cancelled"
    launched: tuple[Any, ...] = ()
    already_launched: tuple[int, ...] = ()
    blocked: tuple[dict[str, Any], ...] = ()
    paused: bool = False
    reason: str | None = None


def batch_needs_resume(manifest: Mapping[str, Any]) -> bool:
    """Return whether a manifest still owns pending dispatch work."""
    status = str(manifest.get("status") or "open")
    if status in {"cancelled", "complete"}:
        return False
    members = manifest.get("members")
    if not isinstance(members, list):
        return False
    return any(
        str(item.get("status") or "pending") in {"pending", "dispatching"}
        for item in members
        if isinstance(item, Mapping)
    )


def batch_clan(manifest: Mapping[str, Any]) -> str | None:
    """Return all clan names recorded by the batch, for notice display."""
    clans = batch_clans(manifest)
    return ", ".join(sorted(clans)) if clans else None


def batch_clans(manifest: Mapping[str, Any]) -> frozenset[str]:
    """Return every clan represented by the accepted batch plan."""
    clans: set[str] = set()
    for key in ("clan", "clan_name"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            clans.add(value)
    members = manifest.get("members")
    if isinstance(members, list):
        for member in members:
            if isinstance(member, Mapping):
                clan = member.get("clan")
                if isinstance(clan, str) and clan:
                    clans.add(clan)
    return frozenset(clans)


def emit_batch_notice(
    *,
    routine: str,
    job: str,
    batch_id: str,
    event: str,
    launched: int,
    remaining: int,
    clan: str | None = None,
    reason: str | None = None,
    hold_key: str | None = None,
    episode_id: str | None = None,
) -> str:
    """Persist and deliver one run log and notification for a batch episode."""
    selected_episode = prepare_batch_notice(
        routine=routine,
        job=job,
        batch_id=batch_id,
        event=event,
        launched=launched,
        remaining=remaining,
        clan=clan,
        reason=reason,
        hold_key=hold_key,
        episode_id=episode_id,
    )
    _deliver_batch_notice(routine, job, batch_id, selected_episode, event)
    return selected_episode


def prepare_batch_notice(
    *,
    routine: str,
    job: str,
    batch_id: str,
    event: str,
    launched: int,
    remaining: int,
    clan: str | None = None,
    reason: str | None = None,
    hold_key: str | None = None,
    episode_id: str | None = None,
) -> str:
    """Persist an outbox intent before replay or another external effect."""
    timestamp = datetime.now(get_timezone()).isoformat()
    selected_episode = episode_id or ""

    def _update(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal selected_episode
        episodes = state.get("episodes")
        if not isinstance(episodes, dict):
            episodes = {}
        state["episodes"] = episodes

        if event == "hold":
            active = state.get("active_hold")
            if (
                isinstance(active, dict)
                and active.get("key") == (hold_key or reason or "hold")
                and isinstance(active.get("episode_id"), str)
            ):
                selected_episode = str(active["episode_id"])
            else:
                selected_episode = selected_episode or str(uuid4())
                state["active_hold"] = {
                    "key": hold_key or reason or "hold",
                    "episode_id": selected_episode,
                }
        elif event == "interrupted" and not selected_episode:
            current_id = state.get("current_episode_id")
            current = episodes.get(current_id) if isinstance(current_id, str) else None
            current_events = (
                current.get("events") if isinstance(current, dict) else None
            )
            if not isinstance(current_events, dict) or "resumed" in current_events:
                selected_episode = str(uuid4())
                state["current_episode_id"] = selected_episode
            else:
                selected_episode = str(current_id)
        elif event == "resumed" and not selected_episode:
            current_id = state.get("current_episode_id")
            selected_episode = (
                str(current_id) if isinstance(current_id, str) else str(uuid4())
            )
            state["current_episode_id"] = selected_episode
        elif event == "cancelled" and not selected_episode:
            current_id = state.get("cancelled_episode_id")
            selected_episode = (
                str(current_id) if isinstance(current_id, str) else str(uuid4())
            )
            state["cancelled_episode_id"] = selected_episode
        elif not selected_episode:
            selected_episode = str(uuid4())

        episode = episodes.get(selected_episode)
        if not isinstance(episode, dict):
            episode = {"created_at": timestamp, "events": {}}
            episodes[selected_episode] = episode
        events = episode.get("events")
        if not isinstance(events, dict):
            events = {}
            episode["events"] = events
        old = events.get(event)
        if isinstance(old, dict) and old.get("delivered"):
            return state
        event_data = dict(old) if isinstance(old, dict) else {}
        event_data.update(
            {
                "event": event,
                "notice_id": event_data.get("notice_id") or str(uuid4()),
                "dedupe_key": (
                    f"chop-batch:{event}:{routine}:{job}:{batch_id}:{selected_episode}"
                ),
                "timestamp": event_data.get("timestamp") or timestamp,
                "launched": launched,
                "remaining": remaining,
                "clan": clan,
                "reason": reason,
                "delivered": False,
            }
        )
        events[event] = event_data
        return state

    update_chop_batch_notice_state(routine, job, batch_id, _update)
    return selected_episode


def deliver_pending_batch_notices(routine: str, job: str, batch_id: str) -> None:
    """Retry all undelivered outbox events idempotently."""
    for pending in pending_chop_batch_notices(routine, job, batch_id):
        event = str(pending.get("event") or "")
        episode_id = str(pending.get("episode_id") or "")
        if event and episode_id:
            _deliver_batch_notice(routine, job, batch_id, episode_id, event)


def clear_batch_recovery_hold(routine: str, job: str, batch_id: str) -> None:
    """End the current hold episode after the batch becomes actionable."""
    current = load_chop_batch_notice_state(routine, job, batch_id)
    if not isinstance(current.get("active_hold"), dict):
        return

    def _clear(state: dict[str, Any]) -> dict[str, Any]:
        state["active_hold"] = None
        return state

    update_chop_batch_notice_state(routine, job, batch_id, _clear)


def pending_interruption_episode(routine: str, job: str, batch_id: str) -> str | None:
    """Return the current interruption episode until recovery is announced."""
    state = load_chop_batch_notice_state(routine, job, batch_id)
    episode_id = state.get("current_episode_id")
    episodes = state.get("episodes")
    episode = episodes.get(episode_id) if isinstance(episodes, dict) else None
    events = episode.get("events") if isinstance(episode, dict) else None
    interrupted = events.get("interrupted") if isinstance(events, dict) else None
    resumed = events.get("resumed") if isinstance(events, dict) else None
    if (
        isinstance(episode_id, str)
        and isinstance(interrupted, dict)
        and interrupted.get("delivered")
        and not (isinstance(resumed, dict) and resumed.get("delivered"))
    ):
        return episode_id
    return None


def _deliver_batch_notice(
    routine: str, job: str, batch_id: str, episode_id: str, event_name: str
) -> None:
    state = load_chop_batch_notice_state(routine, job, batch_id)
    episodes = state.get("episodes")
    episode = episodes.get(episode_id) if isinstance(episodes, dict) else None
    events = episode.get("events") if isinstance(episode, dict) else None
    event = events.get(event_name) if isinstance(events, dict) else None
    if not isinstance(event, dict) or event.get("delivered"):
        return

    timestamp = str(event.get("timestamp") or datetime.now(get_timezone()).isoformat())
    launched = int(event.get("launched") or 0)
    remaining = int(event.get("remaining") or 0)
    clan = event.get("clan") if isinstance(event.get("clan"), str) else None
    reason = event.get("reason") if isinstance(event.get("reason"), str) else None
    notice_id = str(event.get("notice_id") or uuid4())
    dedupe_key = str(event.get("dedupe_key") or "")
    marker = f"[chop-batch-notice:{notice_id}]"
    clan_part = f" clan {clan}" if clan else ""
    reason_part = f" Reason: {reason}." if reason else ""
    line = (
        f"Chop batch {event_name}: routine {routine} job {job} run {batch_id}"
        f"{clan_part}: {launched} launched, {remaining} remaining."
        f"{reason_part} {marker}\n"
    )
    from .state import append_chop_run_output, chop_run_log_path

    log_path = chop_run_log_path(routine, job, batch_id)
    try:
        already_logged = marker in log_path.read_text(encoding="utf-8")
    except OSError:
        already_logged = False
    if not already_logged:
        append_chop_run_output(routine, job, batch_id, line)

    from sase.notifications.models import Notification
    from sase.notifications.store import reconcile_notification_rows

    notes = [
        f"Chop launch batch {event_name}: {routine}/{job} run {batch_id}.",
        f"{launched} launched, {remaining} remaining.",
    ]
    if clan:
        notes.append(f"Clan: {clan}.")
    if reason:
        notes.append(f"Hold or failure: {reason}.")
    if event_name == "interrupted":
        notes.append("The batch will resume automatically when its hold clears.")
    elif event_name == "resumed":
        notes.append(
            "Recovery resumed the remaining members under their original identities."
        )
    elif event_name == "cancelled":
        notes.append("Remaining launch intent was discarded by an explicit clan kill.")
    elif event_name == "hold":
        notes.append("Recovery is held until the reported condition is resolved.")
    notification = Notification(
        id=notice_id,
        timestamp=timestamp,
        sender="chop-batch-recovery",
        icon="!",
        color="#D14343"
        if event_name in {"interrupted", "cancelled", "hold"}
        else "#2E7D32",
        notes=notes,
        files=[],
        tags=["chop", "batch", event_name],
        dedup_key=dedupe_key,
    )
    # A stable row id plus field-scoped reconciliation makes delivery safe to
    # retry after a crash between the notification write and the outbox ack.
    # Notification dedup keys deliberately create +1 events, which would turn
    # an outbox retry into a second visible episode count.
    reconcile_notification_rows([notification])

    def _mark_delivered(current: dict[str, Any]) -> dict[str, Any]:
        current_episodes = current.get("episodes")
        current_episode = (
            current_episodes.get(episode_id)
            if isinstance(current_episodes, dict)
            else None
        )
        current_events = (
            current_episode.get("events") if isinstance(current_episode, dict) else None
        )
        current_event = (
            current_events.get(event_name) if isinstance(current_events, dict) else None
        )
        if isinstance(current_event, dict):
            current_event["delivered"] = True
        return current

    update_chop_batch_notice_state(routine, job, batch_id, _mark_delivered)


def summarize_manifest(manifest: Mapping[str, Any]) -> dict[str, int]:
    try:
        from sase.core.axe_chop_facade import summarize_chop_batch

        summary = summarize_chop_batch(dict(manifest))
        counts = summary.get("counts") or {}
        launched = int(counts.get("launched", 0))
        pending = int(counts.get("pending", 0))
        dispatching = int(counts.get("dispatching", 0))
        return {"launched": launched, "remaining": pending + dispatching}
    except Exception:
        members = manifest.get("members")
        launched = 0
        remaining = 0
        if isinstance(members, list):
            for item in members:
                if not isinstance(item, Mapping):
                    continue
                status = str(item.get("status") or "")
                if status == "launched":
                    launched += 1
                elif status in {"pending", "dispatching"}:
                    remaining += 1
        return {"launched": launched, "remaining": remaining}
