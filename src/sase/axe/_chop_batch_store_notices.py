"""Durable notice outbox and dispatch attempts for chop batches."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ._chop_batch_store_paths import (
    chop_batch_attempts_path,
    chop_batch_notices_path,
    mutation_lock_path,
)
from ._chop_batch_store_shared import (
    ChopBatchError,
    atomic_write_manifest,
    locked,
    read_json_object,
)


def increment_chop_batch_dispatch_attempt(
    routine: str, job: str, batch_id: str, member_index: int
) -> int:
    """Durably count a failed recovery dispatch for one accepted member."""
    path = chop_batch_attempts_path(routine, job, batch_id)
    with locked(mutation_lock_path(routine, job)):
        data = read_json_object(path)
        attempts = data.get("attempts")
        if not isinstance(attempts, dict):
            attempts = {}
        key = str(member_index)
        current = attempts.get(key, 0)
        count = (
            int(current)
            if isinstance(current, int) and not isinstance(current, bool)
            else 0
        )
        attempts[key] = count + 1
        atomic_write_manifest(path, {"batch_id": batch_id, "attempts": attempts})
        return count + 1


def chop_batch_dispatch_attempts(
    routine: str, job: str, batch_id: str
) -> dict[int, int]:
    """Return persisted recovery attempt counts keyed by member index."""
    data = read_json_object(chop_batch_attempts_path(routine, job, batch_id))
    attempts = data.get("attempts")
    if not isinstance(attempts, dict):
        return {}
    result: dict[int, int] = {}
    for key, value in attempts.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            continue
        if index >= 0 and isinstance(value, int) and not isinstance(value, bool):
            result[index] = max(0, value)
    return result


def load_chop_batch_notice_state(
    routine: str, job: str, batch_id: str
) -> dict[str, Any]:
    """Load the durable outbox state, returning an empty state when absent."""
    return read_json_object(chop_batch_notices_path(routine, job, batch_id))


def pending_chop_batch_notices(
    routine: str, job: str, batch_id: str
) -> list[dict[str, Any]]:
    """Return notice outbox entries that still need external delivery."""
    state = load_chop_batch_notice_state(routine, job, batch_id)
    episodes = state.get("episodes")
    if not isinstance(episodes, dict):
        return []
    pending: list[dict[str, Any]] = []
    for episode_id, episode in episodes.items():
        if not isinstance(episode, dict):
            continue
        events = episode.get("events")
        if not isinstance(events, dict):
            continue
        for event_name, event in events.items():
            if isinstance(event, dict) and not event.get("delivered"):
                pending.append(
                    {"episode_id": str(episode_id), "event": str(event_name), **event}
                )
    return pending


def update_chop_batch_notice_state(
    routine: str,
    job: str,
    batch_id: str,
    transform: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Atomically update the per-batch notice outbox sidecar."""
    path = chop_batch_notices_path(routine, job, batch_id)
    with locked(mutation_lock_path(routine, job)):
        current = read_json_object(path)
        updated = transform(dict(current))
        if not isinstance(updated, dict):
            raise ChopBatchError("notice state transform must return an object")
        updated.setdefault("schema_version", 1)
        updated.setdefault("batch_id", batch_id)
        atomic_write_manifest(path, updated)
        return updated
