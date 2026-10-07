"""Shared event-ID minting and serialization helpers for the bead corpus."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

_EPOCH = datetime(2025, 8, 1, tzinfo=UTC)

__all__ = ["bead_slug", "dump_payload", "format_timestamp", "mint_event_id"]


def format_timestamp(offset: timedelta) -> str:
    moment = _EPOCH + offset
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def mint_event_id(
    stream_id: str,
    ordinal: int,
    timestamp: str,
    actor: str,
    operation: str,
    issue_id: str,
    payload: dict[str, Any],
) -> str:
    """Mint an event ID exactly as core's ``mint_bead_event_id`` does."""
    content = json.dumps(
        [1, timestamp, actor, operation, issue_id, payload],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    return f"{stream_id}:{ordinal:06d}:{operation}:{issue_id}:{digest}"


def dump_payload(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def bead_slug(bead_id: str) -> str:
    return bead_id.replace(".", "_")
