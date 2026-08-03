"""Queue operations for durable sidecar publication requests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
import os
import time

from sase.agents_sync.publication_outbox_diagnostics import (
    publication_status_diagnostic,
    publication_stopped_diagnostic,
)
from sase.agents_sync.publication_outbox_models import (
    AgentPublicationOutboxItem,
    SidecarPublicationRequest,
    bead_pages_publication_request,
    plan_header_publication_request,
    publication_sort_key,
    sidecar_push_publication_request,
    validate_publication_item,
)
from sase.agents_sync.publication_outbox_store import (
    list_agent_publications,
    mutate_publication_outbox,
)

DEFAULT_PUBLICATION_MAX_ATTEMPTS = 3
_PUBLICATION_MAX_ATTEMPTS_ENV = "SASE_AGENTS_PUBLICATION_MAX_ATTEMPTS"


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
        for candidate in mutate_publication_outbox(item.project_key, update)
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

    return mutate_publication_outbox(project_key, update)


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

    return mutate_publication_outbox(project_key, update)


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

    mutate_publication_outbox(project_key, update)
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
    return mutate_publication_outbox(
        project_key,
        lambda items: tuple(item for item in items if item.logical_key not in selected),
    )


__all__ = [
    "DEFAULT_PUBLICATION_MAX_ATTEMPTS",
    "acknowledge_agent_publications",
    "clear_quarantined_agent_publications",
    "configured_publication_max_attempts",
    "drop_terminal_agent_publications",
    "enqueue_agent_publication",
    "enqueue_bead_pages_publication",
    "enqueue_plan_header_publication",
    "enqueue_sidecar_push_publication",
    "publication_quarantine_diagnostics",
    "publication_status_diagnostics",
    "update_agent_publications",
]
