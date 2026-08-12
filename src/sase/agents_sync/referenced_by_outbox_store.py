"""Locked persistence primitives for the Referenced By outbox."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import fcntl
from pathlib import Path

from sase.agents_sync.io import atomic_write_json
from sase.agents_sync.referenced_by_outbox_models import (
    REFERENCED_BY_OUTBOX_SCHEMA_VERSION,
    ReferencedByOutboxItem,
)
from sase.agents_sync.referenced_by_outbox_serialization import (
    ReferencedByOutboxDocument,
    read_referenced_by_outbox,
    read_referenced_by_outbox_document,
)
from sase.core.paths import sase_projects_dir, validate_sase_project_name

REFERENCED_BY_OUTBOX_FILENAME = "referenced-by-outbox.json"


def list_referenced_by_requests(
    project_key: str,
    *,
    include_quarantined: bool = True,
) -> tuple[ReferencedByOutboxItem, ...]:
    """Return the durable back-reference requests queued for *project_key*."""

    with _outbox_lock(project_key):
        items = read_referenced_by_outbox(_outbox_path(project_key), project_key)
    if include_quarantined:
        return items
    return tuple(item for item in items if not item.quarantined and not item.terminal)


def snapshot_referenced_by_requests_from_path(
    path: Path | str,
    project_key: str,
) -> tuple[ReferencedByOutboxItem, ...]:
    """Read one immutable referenced-by outbox snapshot without taking its lock."""

    validate_sase_project_name(project_key)
    return read_referenced_by_outbox(Path(path), project_key)


def snapshot_referenced_by_document_from_path(
    path: Path | str,
    project_key: str,
) -> ReferencedByOutboxDocument:
    """Read one lock-free referenced-by outbox document snapshot."""

    validate_sase_project_name(project_key)
    return read_referenced_by_outbox_document(Path(path), project_key)


def mutate_referenced_by_outbox(
    project_key: str,
    update: Callable[
        [tuple[ReferencedByOutboxItem, ...]],
        tuple[ReferencedByOutboxItem, ...],
    ],
) -> tuple[ReferencedByOutboxItem, ...]:
    """Apply *update* while holding the project outbox's exclusive lock."""

    with _outbox_lock(project_key):
        path = _outbox_path(project_key)
        items = update(read_referenced_by_outbox(path, project_key))
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            path,
            {
                "schema_version": REFERENCED_BY_OUTBOX_SCHEMA_VERSION,
                "items": [item.to_json_dict() for item in items],
            },
        )
        return items


def _outbox_path(project_key: str) -> Path:
    validate_sase_project_name(project_key)
    return sase_projects_dir() / project_key / REFERENCED_BY_OUTBOX_FILENAME


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


__all__ = [
    "REFERENCED_BY_OUTBOX_FILENAME",
    "list_referenced_by_requests",
    "mutate_referenced_by_outbox",
    "snapshot_referenced_by_document_from_path",
    "snapshot_referenced_by_requests_from_path",
]
