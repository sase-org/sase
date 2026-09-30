"""Durable outbox for private attachment uploads.

Path ``<sase home>/projects/<key>/attachment-upload-outbox.json`` via
:func:`sase_projects_dir`, so ``SASE_HOME`` is honored. Flock plus atomic
replace, following ``agents_sync.publication_outbox_store``. Records are
digest, size, store name (``git``), and origin machine. No filenames.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fcntl

from sase.agents_sync.io import atomic_write_json
from sase.core.paths import sase_projects_dir, validate_sase_project_name

log = logging.getLogger(__name__)

OUTBOX_FILENAME = "attachment-upload-outbox.json"
OUTBOX_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class OutboxEntry:
    """One queued upload: digest, size, store name, and origin machine."""

    digest: str
    size_bytes: int
    store: str = "git"
    origin: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "store": self.store,
        }
        if self.origin is not None:
            payload["origin"] = self.origin
        return payload

    @staticmethod
    def from_json_dict(value: object) -> OutboxEntry:
        if not isinstance(value, dict):
            raise ValueError("outbox entry must be an object")
        digest = value.get("digest")
        size = value.get("size_bytes")
        store = value.get("store", "git")
        origin = value.get("origin")
        if not isinstance(digest, str) or not digest:
            raise ValueError("outbox entry digest must be a non-empty string")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("outbox entry size_bytes must be a non-negative int")
        if not isinstance(store, str) or not store:
            raise ValueError("outbox entry store must be a non-empty string")
        if origin is not None and not isinstance(origin, str):
            raise ValueError("outbox entry origin must be a string")
        return OutboxEntry(
            digest=digest,
            size_bytes=size,
            store=str(store),
            origin=origin,
        )


def _outbox_path(project_key: str) -> Path:
    """Return the outbox path for *project_key*."""
    validate_sase_project_name(project_key)
    return sase_projects_dir() / project_key / OUTBOX_FILENAME


@contextmanager
def _outbox_lock(project_key: str) -> Iterator[None]:
    path = _outbox_path(project_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_locked(path: Path) -> list[OutboxEntry]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"attachment outbox is malformed: {exc}") from exc
    if isinstance(document, dict) and "items" in document:
        items = document.get("items")
    elif isinstance(document, list):
        items = document
    else:
        raise ValueError("attachment outbox is malformed: expected object")
    if not isinstance(items, list):
        raise ValueError("attachment outbox is malformed: items must be a list")
    return [OutboxEntry.from_json_dict(item) for item in items]


def _write_locked(path: Path, entries: list[OutboxEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {
            "schema_version": OUTBOX_SCHEMA_VERSION,
            "items": [entry.to_json_dict() for entry in entries],
        },
    )


def read_outbox(project_key: str) -> list[OutboxEntry]:
    """Return queued entries; missing file reads as empty.

    A malformed file raises ValueError so callers can warn without losing it.
    """
    with _outbox_lock(project_key):
        return _read_locked(_outbox_path(project_key))


def enqueue_outbox(project_key: str, entries: list[OutboxEntry]) -> list[OutboxEntry]:
    """Append entries whose digests are not already queued."""
    if not entries:
        with _outbox_lock(project_key):
            return _read_locked(_outbox_path(project_key))
    with _outbox_lock(project_key):
        path = _outbox_path(project_key)
        current = _read_locked(path)
        known = {entry.digest for entry in current}
        merged = list(current)
        for entry in entries:
            if entry.digest not in known:
                merged.append(entry)
                known.add(entry.digest)
        _write_locked(path, merged)
        return merged


def remove_outbox_digests(
    project_key: str, digests: list[str] | set[str]
) -> list[OutboxEntry]:
    """Drop *digests* from the queue, returning the remainder."""
    wanted = set(digests)
    with _outbox_lock(project_key):
        path = _outbox_path(project_key)
        current = _read_locked(path)
        remaining = [entry for entry in current if entry.digest not in wanted]
        if len(remaining) != len(current):
            _write_locked(path, remaining)
        return remaining


def drain_outbox(
    project_key: str,
    store: Any,
    *,
    time_bound_seconds: float = 5.0,
    only_digests: set[str] | None = None,
) -> tuple[int, int]:
    """Upload queued entries through *store*, returning (drained, remaining).

    A drain failure is logged and never raises: the caller keeps publishing.
    Entries whose local object is missing stay queued. The run stops when the
    time bound expires; leftovers stay queued.
    """
    deadline = time.monotonic() + max(0.0, time_bound_seconds)
    try:
        with _outbox_lock(project_key):
            path = _outbox_path(project_key)
            entries = _read_locked(path)
    except ValueError as exc:
        log.warning("attachment outbox drain skipped: %s", exc)
        return (0, 0)
    except OSError as exc:
        log.warning("attachment outbox drain skipped: %s", exc)
        return (0, 0)
    if only_digests is not None:
        targets = [entry for entry in entries if entry.digest in only_digests]
    else:
        targets = list(entries)
    if not targets:
        return (0, len(entries))
    from sase.bead.attachments.store import LocalAttachmentStore

    local = LocalAttachmentStore()
    drained: list[str] = []
    for entry in targets:
        if time.monotonic() >= deadline:
            break
        if getattr(store, "name", "git") != entry.store:
            continue
        src = local.object_path(entry.digest)
        if not src.is_file():
            continue
        try:
            put = store.put
            put(entry.digest, src, entry.size_bytes)
        except Exception as exc:
            log.warning(
                "attachment outbox upload of %s… failed: %s",
                entry.digest[:12],
                exc,
            )
            continue
        drained.append(entry.digest)
    if drained:
        try:
            remaining = remove_outbox_digests(project_key, drained)
            return (len(drained), len(remaining))
        except (OSError, ValueError) as exc:
            log.warning("attachment outbox drain cleanup failed: %s", exc)
            return (0, len(entries))
    return (0, len(entries))


__all__ = [
    "OUTBOX_FILENAME",
    "OUTBOX_SCHEMA_VERSION",
    "OutboxEntry",
    "drain_outbox",
    "enqueue_outbox",
    "_outbox_path",
    "read_outbox",
    "remove_outbox_digests",
]
