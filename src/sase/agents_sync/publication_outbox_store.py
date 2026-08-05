"""Locked persistence primitives for the sidecar publication outbox."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import fcntl
from pathlib import Path

from sase.agents_sync.io import atomic_write_json
from sase.agents_sync.publication_outbox_models import (
    PUBLICATION_OUTBOX_SCHEMA_VERSION,
    AgentPublicationOutboxItem,
)
from sase.agents_sync.publication_outbox_serialization import (
    PublicationOutboxDocument,
    read_publication_outbox,
    read_publication_outbox_document,
)
from sase.core.paths import sase_projects_dir
from sase.core.paths import validate_sase_project_name

AGENT_PUBLICATION_OUTBOX_FILENAME = "agents-publication-outbox.json"


def list_agent_publications(
    project_key: str,
    *,
    include_quarantined: bool = True,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Return the durable requests currently queued for *project_key*."""

    with _outbox_lock(project_key):
        items = read_publication_outbox(_outbox_path(project_key), project_key)
    if include_quarantined:
        return items
    return tuple(item for item in items if not item.quarantined and not item.terminal)


def snapshot_agent_publications_from_path(
    path: Path | str,
    project_key: str,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Read one immutable typed outbox snapshot without taking its lock.

    Writers atomically replace the complete JSON document with ``os.replace``,
    so a reader observes either the previous complete document or the next
    complete document. This read-only path neither creates a lock file nor
    writes to the project directory.

    Callers pass *path* explicitly because readers already resolve it while
    scanning the projects root, and because ``sase doctor`` reads a projects
    root it was handed rather than the ambient one.
    """

    validate_sase_project_name(project_key)
    return read_publication_outbox(Path(path), project_key)


def snapshot_publication_document_from_path(
    path: Path | str,
    project_key: str,
) -> PublicationOutboxDocument:
    """Read one lock-free outbox snapshot together with its migration notices."""

    validate_sase_project_name(project_key)
    return read_publication_outbox_document(Path(path), project_key)


def mutate_publication_outbox(
    project_key: str,
    update: Callable[
        [tuple[AgentPublicationOutboxItem, ...]],
        tuple[AgentPublicationOutboxItem, ...],
    ],
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Apply *update* while holding the project outbox's exclusive lock."""

    with _outbox_lock(project_key):
        path = _outbox_path(project_key)
        items = update(read_publication_outbox(path, project_key))
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
    return sase_projects_dir() / project_key / AGENT_PUBLICATION_OUTBOX_FILENAME


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
    "AGENT_PUBLICATION_OUTBOX_FILENAME",
    "list_agent_publications",
    "mutate_publication_outbox",
    "snapshot_agent_publications_from_path",
    "snapshot_publication_document_from_path",
]
