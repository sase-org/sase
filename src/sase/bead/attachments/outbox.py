"""Durable outbox for attachment uploads.

Path ``<sase home>/projects/<key>/attachment-upload-outbox.json`` via
:func:`sase_projects_dir`, so ``SASE_HOME`` is honored. Flock plus atomic
replace, following ``agents_sync.publication_outbox_store``. Records are
digest, size, store name (``git``/``public``/``large``), origin machine,
optional MIME type, and optional state. No filenames.
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
    """One queued upload: digest, size, store name, origin, MIME, and state."""

    digest: str
    size_bytes: int
    store: str = "git"
    origin: str | None = None
    mime_type: str | None = None
    state: str = "pending"

    def to_json_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "digest": self.digest,
            "size_bytes": self.size_bytes,
            "store": self.store,
        }
        if self.origin is not None:
            payload["origin"] = self.origin
        if self.mime_type is not None:
            payload["mime_type"] = self.mime_type
        if self.state != "pending":
            payload["state"] = self.state
        return payload

    @staticmethod
    def from_json_dict(value: object) -> OutboxEntry:
        if not isinstance(value, dict):
            raise ValueError("outbox entry must be an object")
        digest = value.get("digest")
        size = value.get("size_bytes")
        store = value.get("store", "git")
        origin = value.get("origin")
        mime_type = value.get("mime_type")
        state = value.get("state", "pending")
        if not isinstance(digest, str) or not digest:
            raise ValueError("outbox entry digest must be a non-empty string")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("outbox entry size_bytes must be a non-negative int")
        if not isinstance(store, str) or not store:
            raise ValueError("outbox entry store must be a non-empty string")
        if origin is not None and not isinstance(origin, str):
            raise ValueError("outbox entry origin must be a string")
        if mime_type is not None and not isinstance(mime_type, str):
            raise ValueError("outbox entry mime_type must be a string")
        if state not in ("pending", "blocked"):
            state = "pending"
        return OutboxEntry(
            digest=digest,
            size_bytes=size,
            store=str(store),
            origin=origin,
            mime_type=mime_type,
            state=str(state),
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
    """Append entries whose ``(digest, store)`` identity is not already queued.

    A ``blocked`` row is never resurrected as ``pending``.
    """
    if not entries:
        with _outbox_lock(project_key):
            return _read_locked(_outbox_path(project_key))
    with _outbox_lock(project_key):
        path = _outbox_path(project_key)
        current = _read_locked(path)
        known = {(entry.digest, entry.store) for entry in current}
        blocked = {
            (entry.digest, entry.store) for entry in current if entry.state == "blocked"
        }
        merged = list(current)
        for entry in entries:
            identity = (entry.digest, entry.store)
            if identity in known:
                continue
            if identity in blocked and entry.state != "blocked":
                continue
            merged.append(entry)
            known.add(identity)
            if entry.state == "blocked":
                blocked.add(identity)
        _write_locked(path, merged)
        return merged


def mark_outbox_blocked(project_key: str, digest: str, store: str) -> None:
    """Mark one ``(digest, store)`` outbox entry ``blocked``."""
    with _outbox_lock(project_key):
        path = _outbox_path(project_key)
        current = _read_locked(path)
        changed = False
        updated: list[OutboxEntry] = []
        for entry in current:
            if entry.digest == digest and entry.store == store:
                if entry.state != "blocked":
                    entry = OutboxEntry(
                        digest=entry.digest,
                        size_bytes=entry.size_bytes,
                        store=entry.store,
                        origin=entry.origin,
                        mime_type=entry.mime_type,
                        state="blocked",
                    )
                    changed = True
            updated.append(entry)
        if changed:
            _write_locked(path, updated)


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


def _remove_outbox_entries(
    project_key: str, identities: set[tuple[str, str]]
) -> list[OutboxEntry]:
    """Drop ``(digest, store)`` identities, returning the remainder."""
    with _outbox_lock(project_key):
        path = _outbox_path(project_key)
        current = _read_locked(path)
        remaining = [
            entry for entry in current if (entry.digest, entry.store) not in identities
        ]
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

    Only entries whose ``store`` equals ``store.name`` are attempted, and
    ``blocked`` entries are skipped. A drain failure is logged and never
    raises: the caller keeps publishing. Entries whose local object is
    missing stay queued. The run stops when the time bound expires;
    leftovers stay queued.
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
    drained: set[tuple[str, str]] = set()
    for entry in targets:
        if time.monotonic() >= deadline:
            break
        if getattr(store, "name", "git") != entry.store:
            continue
        if entry.state == "blocked":
            continue
        src = local.object_path(entry.digest)
        if not src.is_file():
            continue
        try:
            put = store.put
            try:
                put(
                    entry.digest,
                    src,
                    entry.size_bytes,
                    mime_type=entry.mime_type,
                )
            except TypeError:
                put(entry.digest, src, entry.size_bytes)
        except Exception as exc:
            if getattr(exc, "secret_scan", False):
                try:
                    from sase.bead.attachments.upload.secret_scan import (
                        handle_secret_scan_rejection,
                    )
                except Exception:
                    handle_secret_scan_rejection = None  # type: ignore[assignment]
                if handle_secret_scan_rejection is not None:
                    try:
                        handle_secret_scan_rejection(
                            project_key, entry, store, str(exc)
                        )
                    except Exception:
                        pass
                continue
            log.warning(
                "attachment outbox upload of %s… failed: %s",
                entry.digest[:12],
                exc,
            )
            continue
        drained.add((entry.digest, entry.store))
    if drained:
        try:
            remaining = _remove_outbox_entries(project_key, drained)
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
    "mark_outbox_blocked",
    "_outbox_path",
    "read_outbox",
    "remove_outbox_digests",
]
