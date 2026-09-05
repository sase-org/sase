"""Checkpoint persistence for runner-owned chop policy decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sase.core.axe_chop_facade import (
    CHOP_ENGINE_SCHEMA_VERSION,
    apply_chop_checkpoint_update,
)
from sase.core.time import get_timezone

from .chop_policy_state import (
    atomic_write_json,
    checkpoint_path,
    chop_policy_lock,
    read_checkpoint_document,
)
from .chop_policy_types import ChopCheckpointEvent, ChopPreflight


def record_chop_checkpoint_event(
    lumberjack_name: str,
    chop_name: str,
    preflight: ChopPreflight,
    event: ChopCheckpointEvent,
    *,
    now: datetime | None = None,
) -> None:
    """Persist one checkpoint lifecycle event returned by the Rust engine."""
    decision = preflight.decision
    if not preflight.checkpoint_enabled or decision is None:
        return
    key = decision.get("checkpoint_key")
    cursor = decision.get("checkpoint_cursor")
    policy = decision.get("checkpoint_policy")
    if not key or not cursor or not policy:
        return

    with chop_policy_lock(lumberjack_name, chop_name):
        document = read_checkpoint_document(lumberjack_name, chop_name)
        updated = apply_chop_checkpoint_update(
            {
                "schema_version": CHOP_ENGINE_SCHEMA_VERSION,
                "document": document,
                "key": str(key),
                "cursor": str(cursor),
                "now": (now or datetime.now(get_timezone())).isoformat(),
                "policy": str(policy),
                "event": event,
            }
        )
        atomic_write_json(checkpoint_path(lumberjack_name, chop_name), updated)


def finalize_pending_chop_checkpoints(
    lumberjack_name: str,
    chop_name: str,
    event: Literal["action_succeeded", "action_failed"],
    *,
    now: datetime | None = None,
) -> int:
    """Finalize every pending on-action-success cursor for one chop."""
    with chop_policy_lock(lumberjack_name, chop_name):
        document = read_checkpoint_document(lumberjack_name, chop_name)
        entries = document.get("entries")
        if not isinstance(entries, dict):
            raise ValueError("checkpoint document entries must be an object")
        pending = [
            (str(key), str(entry["pending_cursor"]))
            for key, entry in entries.items()
            if isinstance(entry, dict) and entry.get("pending_cursor")
        ]
        if not pending:
            return 0

        timestamp = (now or datetime.now(get_timezone())).isoformat()
        updated = document
        for key, cursor in pending:
            updated = apply_chop_checkpoint_update(
                {
                    "schema_version": CHOP_ENGINE_SCHEMA_VERSION,
                    "document": updated,
                    "key": key,
                    "cursor": cursor,
                    "now": timestamp,
                    "policy": "on_action_success",
                    "event": event,
                }
            )
        atomic_write_json(checkpoint_path(lumberjack_name, chop_name), updated)
        return len(pending)


__all__ = [
    "finalize_pending_chop_checkpoints",
    "record_chop_checkpoint_event",
]
