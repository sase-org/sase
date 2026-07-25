"""Durable retry outbox for post-commit agent-hood publication."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

from sase.agents_sync.io import atomic_write_json
from sase.core.paths import sase_projects_dir, validate_sase_project_name

PUBLICATION_OUTBOX_SCHEMA_VERSION = 2
DEFAULT_PUBLICATION_MAX_ATTEMPTS = 3
_PUBLICATION_MAX_ATTEMPTS_ENV = "SASE_AGENTS_PUBLICATION_MAX_ATTEMPTS"
_OUTBOX_FILENAME = "agents-publication-outbox.json"


@dataclass(frozen=True, slots=True)
class AgentPublicationOutboxItem:
    """One idempotent primary-commit-to-sidecar publication request."""

    project_key: str
    project: str
    local_agent: str
    global_agent: str
    primary_revision: str
    local_hood: str
    hood_digest: str = "pending"
    attempts: int = 0
    last_error: str | None = None
    quarantined: bool = False
    quarantined_at: float | None = None
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def logical_key(self) -> tuple[str, str]:
        return self.global_agent, self.primary_revision

    @property
    def id(self) -> str:
        payload = "\0".join(
            (
                self.project_key,
                self.global_agent,
                self.primary_revision,
                self.hood_digest,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "project_key": self.project_key,
            "project": self.project,
            "local_agent": self.local_agent,
            "global_agent": self.global_agent,
            "primary_revision": self.primary_revision,
            "local_hood": self.local_hood,
            "hood_digest": self.hood_digest,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "quarantined": self.quarantined,
            "quarantined_at": self.quarantined_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def enqueue_agent_publication(
    item: AgentPublicationOutboxItem,
) -> AgentPublicationOutboxItem:
    """Insert or refresh *item* without duplicating its logical operation."""

    now = time.time()

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        existing = next(
            (
                candidate
                for candidate in items
                if candidate.logical_key == item.logical_key
            ),
            None,
        )
        queued = replace(
            item,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            attempts=existing.attempts if existing is not None else item.attempts,
            last_error=existing.last_error if existing is not None else item.last_error,
            quarantined=(
                existing.quarantined if existing is not None else item.quarantined
            ),
            quarantined_at=(
                existing.quarantined_at if existing is not None else item.quarantined_at
            ),
            hood_digest=(
                existing.hood_digest
                if existing is not None and item.hood_digest == "pending"
                else item.hood_digest
            ),
        )
        return tuple(
            sorted(
                (
                    *(
                        candidate
                        for candidate in items
                        if candidate.logical_key != item.logical_key
                    ),
                    queued,
                ),
                key=lambda candidate: (candidate.created_at, candidate.id),
            )
        )

    return next(
        candidate
        for candidate in _mutate_outbox(item.project_key, update)
        if candidate.logical_key == item.logical_key
    )


def list_agent_publications(
    project_key: str,
    *,
    include_quarantined: bool = True,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Return the durable requests currently queued for *project_key*."""

    with _outbox_lock(project_key):
        items = _read_outbox(_outbox_path(project_key), project_key)
    if include_quarantined:
        return items
    return tuple(item for item in items if not item.quarantined)


def update_agent_publications(
    project_key: str,
    logical_keys: Iterable[tuple[str, str]],
    *,
    hood_digest: str | None = None,
    error: str | None = None,
    increment_attempts: bool = False,
    quarantine_threshold: int | None = None,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Update matching requests atomically and return the resulting outbox."""

    if quarantine_threshold is not None and quarantine_threshold < 1:
        raise ValueError("publication quarantine threshold must be positive")
    selected = frozenset(logical_keys)
    now = time.time()

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        updated: list[AgentPublicationOutboxItem] = []
        for item in items:
            if item.logical_key not in selected:
                updated.append(item)
                continue
            attempts = item.attempts + int(increment_attempts)
            quarantine = item.quarantined or (
                quarantine_threshold is not None and attempts >= quarantine_threshold
            )
            updated.append(
                replace(
                    item,
                    hood_digest=hood_digest or item.hood_digest,
                    last_error=error,
                    attempts=attempts,
                    quarantined=quarantine,
                    quarantined_at=(
                        item.quarantined_at
                        if item.quarantined
                        else now
                        if quarantine
                        else None
                    ),
                    updated_at=now,
                )
            )
        return tuple(updated)

    return _mutate_outbox(project_key, update)


def clear_quarantined_agent_publications(
    project_key: str,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Return quarantined requests to the active queue with a fresh retry budget."""

    now = time.time()

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        return tuple(
            replace(
                item,
                attempts=0,
                last_error=None,
                quarantined=False,
                quarantined_at=None,
                updated_at=now,
            )
            if item.quarantined
            else item
            for item in items
        )

    return _mutate_outbox(project_key, update)


def configured_publication_max_attempts() -> int:
    """Return the bounded per-item preparation retry threshold."""

    raw = os.environ.get(_PUBLICATION_MAX_ATTEMPTS_ENV)
    if raw is None:
        return DEFAULT_PUBLICATION_MAX_ATTEMPTS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_PUBLICATION_MAX_ATTEMPTS
    return value if value > 0 else DEFAULT_PUBLICATION_MAX_ATTEMPTS


def publication_quarantine_diagnostics(project_key: str) -> tuple[str, ...]:
    """Render stable diagnostics for quarantined requests in *project_key*."""

    return tuple(
        (
            f"publication request {item.global_agent}@"
            f"{item.primary_revision[:12]} quarantined after {item.attempts} "
            f"attempts: {item.last_error or 'unknown error'}; run "
            "`sase agent sync --retry-quarantined` to retry"
        )
        for item in list_agent_publications(project_key)
        if item.quarantined
    )


def acknowledge_agent_publications(
    project_key: str,
    logical_keys: Iterable[tuple[str, str]],
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Remove successfully published requests and return the remaining outbox."""

    selected = frozenset(logical_keys)
    return _mutate_outbox(
        project_key,
        lambda items: tuple(item for item in items if item.logical_key not in selected),
    )


def _mutate_outbox(
    project_key: str,
    update: Callable[
        [tuple[AgentPublicationOutboxItem, ...]],
        tuple[AgentPublicationOutboxItem, ...],
    ],
) -> tuple[AgentPublicationOutboxItem, ...]:
    with _outbox_lock(project_key):
        path = _outbox_path(project_key)
        items = update(_read_outbox(path, project_key))
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            path,
            {
                "schema_version": PUBLICATION_OUTBOX_SCHEMA_VERSION,
                "items": [item.to_json_dict() for item in items],
            },
        )
        return items


def _outbox_path(project_key: str) -> Path:
    validate_sase_project_name(project_key)
    return sase_projects_dir() / project_key / _OUTBOX_FILENAME


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


def _read_outbox(
    path: Path,
    project_key: str,
) -> tuple[AgentPublicationOutboxItem, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read agents publication outbox: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("agents publication outbox must be a JSON object")
    if payload.get("schema_version") not in {1, PUBLICATION_OUTBOX_SCHEMA_VERSION}:
        raise RuntimeError("unsupported agents publication outbox schema")
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise RuntimeError("agents publication outbox items must be a list")
    items = tuple(_item_from_json(row, project_key) for row in rows)
    if len({item.logical_key for item in items}) != len(items):
        raise RuntimeError("agents publication outbox contains duplicate requests")
    return items


def _item_from_json(
    value: object,
    project_key: str,
) -> AgentPublicationOutboxItem:
    if not isinstance(value, dict):
        raise RuntimeError("agents publication outbox item must be an object")
    row: dict[str, Any] = value
    item = AgentPublicationOutboxItem(
        project_key=str(row.get("project_key") or ""),
        project=str(row.get("project") or ""),
        local_agent=str(row.get("local_agent") or ""),
        global_agent=str(row.get("global_agent") or ""),
        primary_revision=str(row.get("primary_revision") or ""),
        local_hood=str(row.get("local_hood") or ""),
        hood_digest=str(row.get("hood_digest") or "pending"),
        attempts=int(row.get("attempts") or 0),
        last_error=(
            str(row["last_error"]) if row.get("last_error") is not None else None
        ),
        quarantined=bool(row.get("quarantined", False)),
        quarantined_at=(
            float(row["quarantined_at"])
            if row.get("quarantined_at") is not None
            else None
        ),
        created_at=float(row.get("created_at") or 0.0),
        updated_at=float(row.get("updated_at") or 0.0),
    )
    if item.project_key != project_key:
        raise RuntimeError("agents publication outbox project identity mismatch")
    if not all(
        (
            item.project,
            item.local_agent,
            item.global_agent,
            item.primary_revision,
            item.local_hood,
        )
    ):
        raise RuntimeError("agents publication outbox item is incomplete")
    return item


__all__ = [
    "DEFAULT_PUBLICATION_MAX_ATTEMPTS",
    "PUBLICATION_OUTBOX_SCHEMA_VERSION",
    "AgentPublicationOutboxItem",
    "acknowledge_agent_publications",
    "clear_quarantined_agent_publications",
    "configured_publication_max_attempts",
    "enqueue_agent_publication",
    "list_agent_publications",
    "publication_quarantine_diagnostics",
    "update_agent_publications",
]
