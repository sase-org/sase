"""Purge tombstones for bead note attachments.

A purge removes bytes but never edits bead events: a tombstone records that
digest *sha256* was deliberately purged, so every surface renders
``(purged)`` and every fetch refuses the digest. Tombstones live in three
places with one JSON shape (``AttachmentTombstoneWire``: ``schema_version``,
``sha256``, ``purged_at``, ``actor``, ``reason``):

- ``<sase home>/attachments/tombstones/<sha256>.json`` (local record),
- ``files/tombstones/sha256/<xx>/<sha>.json`` in each shared store,
- never inside a bead event.

Commit messages that carry a tombstone name no digest's filenames: only the
digest appears.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, UTC
from pathlib import Path
from typing import Any

from sase.bead.attachments.store import LocalAttachmentStore, validate_sha256

TOMBSTONE_SCHEMA_VERSION = 1


def _tombstone_filename(sha256: str) -> str:
    """Return the local tombstone filename for *sha256*."""
    validate_sha256(sha256)
    return f"{sha256}.json"


def _tombstone_payload(
    sha256: str, reason: str, actor: str | None = None
) -> dict[str, Any]:
    """Return the ``AttachmentTombstoneWire`` payload for *sha256*."""
    validate_sha256(sha256)
    if not reason.strip():
        raise ValueError("purge reason cannot be empty or blank")
    resolved_actor = actor.strip() if isinstance(actor, str) and actor.strip() else None
    if resolved_actor is None:
        try:
            from sase.config import get_machine_name

            machine = get_machine_name()
            if isinstance(machine, str) and machine.strip():
                resolved_actor = machine.strip()
        except Exception:
            resolved_actor = None
    payload: dict[str, Any] = {
        "schema_version": TOMBSTONE_SCHEMA_VERSION,
        "sha256": sha256,
        "purged_at": datetime.now(UTC).isoformat(),
        "reason": reason.strip(),
    }
    if resolved_actor is not None:
        payload["actor"] = resolved_actor
    return payload


def tombstone_bytes(sha256: str, reason: str, actor: str | None = None) -> bytes:
    """Return the canonical JSON bytes for a purge tombstone."""
    return (
        json.dumps(_tombstone_payload(sha256, reason, actor), indent=2) + "\n"
    ).encode("utf-8")


def parse_tombstone_bytes(raw: bytes) -> dict[str, Any]:
    """Parse tombstone JSON, raising ValueError when it is not a tombstone."""
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"not a purge tombstone: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("not a purge tombstone: expected an object")
    if value.get("schema_version") != TOMBSTONE_SCHEMA_VERSION:
        raise ValueError("not a purge tombstone: bad schema_version")
    digest = value.get("sha256")
    if not isinstance(digest, str):
        raise ValueError("not a purge tombstone: bad sha256")
    validate_sha256(digest)
    return value


def _local_tombstone_path(store: LocalAttachmentStore, sha256: str) -> Path:
    """Return the local tombstone path for *sha256*."""
    return store.tombstones_dir / _tombstone_filename(sha256)


def has_local_tombstone(store: LocalAttachmentStore, sha256: str) -> bool:
    """Return whether a local purge tombstone for *sha256* exists."""
    try:
        validate_sha256(sha256)
    except ValueError:
        return False
    try:
        return (store.tombstones_dir / sha256).exists() or _local_tombstone_path(
            store, sha256
        ).exists()
    except OSError:
        return False


def write_local_tombstone(
    store: LocalAttachmentStore,
    sha256: str,
    reason: str,
    actor: str | None = None,
) -> Path:
    """Record a local purge tombstone; return its path (idempotent)."""
    store.ensure_dirs()
    path = _local_tombstone_path(store, sha256)
    if not path.exists():
        path.write_bytes(tombstone_bytes(sha256, reason, actor))
    return path


__all__ = [
    "TOMBSTONE_SCHEMA_VERSION",
    "has_local_tombstone",
    "_local_tombstone_path",
    "parse_tombstone_bytes",
    "tombstone_bytes",
    "_tombstone_filename",
    "_tombstone_payload",
    "write_local_tombstone",
]
