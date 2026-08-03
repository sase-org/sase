"""Durable typed queue for asynchronous sidecar publication.

This module remains the stable public facade. Request modeling, JSON schema
decoding, and diagnostics live in focused sibling modules.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import replace
import fcntl
import os
from pathlib import Path
import time

from sase.agents_sync.io import atomic_write_json
from sase.agents_sync.publication_outbox_diagnostics import (
    PUBLICATION_DROP_COMMAND,
    PUBLICATION_RETRY_COMMAND,
    publication_request_subject,
    publication_status_diagnostic,
    publication_stopped_diagnostic,
)
from sase.agents_sync.publication_outbox_models import (
    PUBLICATION_OUTBOX_SCHEMA_VERSION,
    AgentPublicationOutboxItem,
    PublicationKind,
    PublicationLogicalKey,
    SidecarPublicationRequest,
    bead_pages_publication_request,
    plan_header_publication_request,
    publication_sort_key,
    sidecar_push_publication_request,
    validate_publication_item,
)
from sase.agents_sync.publication_outbox_serialization import (
    read_publication_outbox,
)
from sase.core.paths import sase_projects_dir, validate_sase_project_name

DEFAULT_PUBLICATION_MAX_ATTEMPTS = 3
_PUBLICATION_MAX_ATTEMPTS_ENV = "SASE_AGENTS_PUBLICATION_MAX_ATTEMPTS"
AGENT_PUBLICATION_OUTBOX_FILENAME = "agents-publication-outbox.json"


def _enqueue_sidecar_publication(
    item: SidecarPublicationRequest,
) -> SidecarPublicationRequest:
    """Insert or refresh *item* without duplicating its logical operation."""

    validate_publication_item(item, item.project_key)
    now = time.time()

    def update(
        items: tuple[SidecarPublicationRequest, ...],
    ) -> tuple[SidecarPublicationRequest, ...]:
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
            terminal=existing.terminal if existing is not None else item.terminal,
            terminal_reason=(
                existing.terminal_reason
                if existing is not None
                else item.terminal_reason
            ),
            hood_digest=(
                existing.hood_digest
                if item.kind == "agent_hood"
                and existing is not None
                and item.hood_digest == "pending"
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
                key=publication_sort_key,
            )
        )

    return next(
        candidate
        for candidate in _mutate_outbox(item.project_key, update)
        if candidate.logical_key == item.logical_key
    )


def enqueue_agent_publication(
    item: AgentPublicationOutboxItem,
) -> AgentPublicationOutboxItem:
    """Backward-compatible agent-hood enqueue entry point."""

    if item.kind != "agent_hood":
        raise ValueError("enqueue_agent_publication requires an agent_hood request")
    return _enqueue_sidecar_publication(item)


def enqueue_bead_pages_publication(
    *,
    project_key: str,
    project: str,
    bead_id: str,
    lineage_root: str | None = None,
    primary_revision: str = "",
) -> SidecarPublicationRequest:
    """Enqueue or coalesce one bead lineage."""

    from sase.bead_pages.paths import bead_lineage_root

    derived_root = bead_lineage_root(bead_id)
    if lineage_root is not None and lineage_root != derived_root:
        raise ValueError(
            f"bead lineage root {lineage_root!r} does not match {bead_id!r}"
        )

    return _enqueue_sidecar_publication(
        bead_pages_publication_request(
            project_key=project_key,
            project=project,
            bead_id=bead_id,
            lineage_root=derived_root,
            primary_revision=primary_revision,
        )
    )


def enqueue_plan_header_publication(
    *,
    project_key: str,
    project: str,
    plan_ref: str,
    primary_revision: str,
    commit_message: str,
) -> SidecarPublicationRequest:
    """Enqueue or coalesce one committed-plan header refresh."""

    return _enqueue_sidecar_publication(
        plan_header_publication_request(
            project_key=project_key,
            project=project,
            plan_ref=plan_ref,
            primary_revision=primary_revision,
            commit_message=commit_message,
        )
    )


def enqueue_sidecar_push_publication(
    *,
    project_key: str,
    project: str,
    sidecar_kind: str,
) -> SidecarPublicationRequest:
    """Enqueue or coalesce one sidecar push."""

    return _enqueue_sidecar_publication(
        sidecar_push_publication_request(
            project_key=project_key,
            project=project,
            sidecar_kind=sidecar_kind,
        )
    )


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


def update_agent_publications(
    project_key: str,
    logical_keys: Iterable[tuple[str, str]],
    *,
    hood_digest: str | None = None,
    error: str | None = None,
    increment_attempts: bool = False,
    quarantine_threshold: int | None = None,
    terminal_reason: str | None = None,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Update matching requests atomically and return the resulting outbox.

    ``terminal_reason`` nominates a failure that cannot be fixed by retrying.
    The request is retired only when its prior recorded error is the same, so
    an indexing race still receives one retry before becoming terminal.
    """

    if quarantine_threshold is not None and quarantine_threshold < 1:
        raise ValueError("publication quarantine threshold must be positive")
    if terminal_reason is not None and error != terminal_reason:
        raise ValueError("terminal publication reason must match the recorded error")
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
            terminal = item.terminal or (
                terminal_reason is not None
                and item.attempts > 0
                and item.last_error == terminal_reason
            )
            quarantine = not terminal and (
                item.quarantined
                or (
                    quarantine_threshold is not None
                    and attempts >= quarantine_threshold
                )
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
                        if quarantine and item.quarantined
                        else now
                        if quarantine
                        else None
                    ),
                    terminal=terminal,
                    terminal_reason=(
                        item.terminal_reason
                        if item.terminal
                        else terminal_reason
                        if terminal
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
            if item.quarantined and not item.terminal
            else item
            for item in items
        )

    return _mutate_outbox(project_key, update)


def drop_terminal_agent_publications(
    project_key: str,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Remove retired requests from *project_key* and return the dropped ones."""

    dropped: list[AgentPublicationOutboxItem] = []

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        dropped.extend(item for item in items if item.terminal)
        return tuple(item for item in items if not item.terminal)

    _mutate_outbox(project_key, update)
    return tuple(dropped)


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
    """Render stable diagnostics for stopped requests in *project_key*."""

    return tuple(
        publication_stopped_diagnostic(item)
        for item in list_agent_publications(project_key)
        if item.terminal or item.quarantined
    )


def publication_status_diagnostics(project_key: str) -> tuple[str, ...]:
    """Render operator-facing diagnostics for every queued request."""

    return tuple(
        publication_status_diagnostic(item)
        for item in list_agent_publications(project_key)
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
    "DEFAULT_PUBLICATION_MAX_ATTEMPTS",
    "PUBLICATION_DROP_COMMAND",
    "PUBLICATION_OUTBOX_SCHEMA_VERSION",
    "PUBLICATION_RETRY_COMMAND",
    "AgentPublicationOutboxItem",
    "PublicationKind",
    "PublicationLogicalKey",
    "SidecarPublicationRequest",
    "acknowledge_agent_publications",
    "clear_quarantined_agent_publications",
    "configured_publication_max_attempts",
    "drop_terminal_agent_publications",
    "enqueue_agent_publication",
    "enqueue_bead_pages_publication",
    "enqueue_plan_header_publication",
    "enqueue_sidecar_push_publication",
    "list_agent_publications",
    "publication_quarantine_diagnostics",
    "publication_request_subject",
    "publication_status_diagnostics",
    "snapshot_agent_publications_from_path",
    "update_agent_publications",
]
