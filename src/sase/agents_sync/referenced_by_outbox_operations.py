"""Queue operations for durable Referenced By requests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
import time

from sase.agents_sync.publication_outbox_operations import (
    configured_publication_max_attempts,
)
from sase.agents_sync.referenced_by_outbox_diagnostics import (
    referenced_by_stopped_diagnostic,
)
from sase.agents_sync.referenced_by_outbox_models import (
    ReferencedByLogicalKey,
    ReferencedByOutboxItem,
    referenced_by_sort_key,
    validate_referenced_by_item,
)
from sase.agents_sync.referenced_by_outbox_store import (
    list_referenced_by_requests,
    mutate_referenced_by_outbox,
)


def enqueue_referenced_by_request(
    item: ReferencedByOutboxItem,
) -> ReferencedByOutboxItem:
    """Insert or refresh *item* without duplicating its logical operation."""

    validate_referenced_by_item(item, item.project_key)
    now = time.time()

    def update(
        items: tuple[ReferencedByOutboxItem, ...],
    ) -> tuple[ReferencedByOutboxItem, ...]:
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
                key=referenced_by_sort_key,
            )
        )

    return next(
        candidate
        for candidate in mutate_referenced_by_outbox(item.project_key, update)
        if candidate.logical_key == item.logical_key
    )


def update_referenced_by_requests(
    project_key: str,
    logical_keys: Iterable[ReferencedByLogicalKey],
    *,
    error: str | None = None,
    increment_attempts: bool = False,
    quarantine_threshold: int | None = None,
    terminal_reason: str | None = None,
) -> tuple[ReferencedByOutboxItem, ...]:
    """Update matching requests atomically and return the resulting outbox."""

    if quarantine_threshold is not None and quarantine_threshold < 1:
        raise ValueError("referenced-by quarantine threshold must be positive")
    if terminal_reason is not None and error != terminal_reason:
        raise ValueError("terminal referenced-by reason must match the recorded error")
    selected = frozenset(logical_keys)
    now = time.time()

    def update(
        items: tuple[ReferencedByOutboxItem, ...],
    ) -> tuple[ReferencedByOutboxItem, ...]:
        updated: list[ReferencedByOutboxItem] = []
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

    return mutate_referenced_by_outbox(project_key, update)


def clear_quarantined_referenced_by_requests(
    project_key: str,
) -> tuple[ReferencedByOutboxItem, ...]:
    """Return quarantined requests to the active queue with a fresh retry budget."""

    now = time.time()

    def update(
        items: tuple[ReferencedByOutboxItem, ...],
    ) -> tuple[ReferencedByOutboxItem, ...]:
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

    return mutate_referenced_by_outbox(project_key, update)


def drop_terminal_referenced_by_requests(
    project_key: str,
) -> tuple[ReferencedByOutboxItem, ...]:
    """Remove retired requests from *project_key* and return the dropped ones."""

    dropped: list[ReferencedByOutboxItem] = []

    def update(
        items: tuple[ReferencedByOutboxItem, ...],
    ) -> tuple[ReferencedByOutboxItem, ...]:
        dropped.extend(item for item in items if item.terminal)
        return tuple(item for item in items if not item.terminal)

    mutate_referenced_by_outbox(project_key, update)
    return tuple(dropped)


def referenced_by_quarantine_diagnostics(project_key: str) -> tuple[str, ...]:
    """Render stable diagnostics for stopped referenced-by requests."""

    return tuple(
        referenced_by_stopped_diagnostic(item)
        for item in list_referenced_by_requests(project_key)
        if item.terminal or item.quarantined
    )


def acknowledge_referenced_by_requests(
    project_key: str,
    logical_keys: Iterable[ReferencedByLogicalKey],
) -> tuple[ReferencedByOutboxItem, ...]:
    """Remove successfully reconciled requests and return the remaining outbox."""

    selected = frozenset(logical_keys)
    return mutate_referenced_by_outbox(
        project_key,
        lambda items: tuple(item for item in items if item.logical_key not in selected),
    )


__all__ = [
    "acknowledge_referenced_by_requests",
    "clear_quarantined_referenced_by_requests",
    "configured_publication_max_attempts",
    "drop_terminal_referenced_by_requests",
    "enqueue_referenced_by_request",
    "referenced_by_quarantine_diagnostics",
    "update_referenced_by_requests",
]
