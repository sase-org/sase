"""Queue operations for durable agent-hood publication requests."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
import os
import time

from sase.agents_sync.publication_outbox_diagnostics import (
    publication_stopped_diagnostic,
)
from sase.agents_sync.publication_outbox_models import (
    PUBLICATION_PARK_RECHECK_INTERVAL_SECONDS,
    PUBLICATION_SCOPE_REVISION,
    AgentPublicationOutboxItem,
    publication_sort_key,
    validate_publication_item,
)
from sase.agents_sync.publication_outbox_store import (
    list_agent_publications,
    mutate_publication_outbox,
)
from sase.core.agent_publication_recovery import (
    PublicationDrainSelection,
    PublicationRetrySelected,
    select_publication_drain,
    select_publication_retries,
)

DEFAULT_PUBLICATION_MAX_ATTEMPTS = 3
_PUBLICATION_MAX_ATTEMPTS_ENV = "SASE_AGENTS_PUBLICATION_MAX_ATTEMPTS"


def publication_is_parked_due(
    item: AgentPublicationOutboxItem,
    *,
    now: float | None = None,
    current_rules_version: int | None = None,
    recheck_interval_seconds: float = PUBLICATION_PARK_RECHECK_INTERVAL_SECONDS,
) -> bool:
    """Return whether a parked row is due for one more publish attempt.

    Unparked rows are always due. Parked rows with missing metadata are due
    so a re-park can record complete metadata. Otherwise the Rust
    ``publication_parked_recheck_due`` predicate decides.
    """

    if item.parked_reason is None:
        return True
    if item.parked_checked_at is None or item.parked_rules_version is None:
        return True
    from sase.core.agent_publication_recovery import (
        attachment_scanner_rules_version,
        publication_parked_recheck_due,
    )

    observed = time.time() if now is None else now
    current = current_rules_version
    if current is None:
        try:
            current = attachment_scanner_rules_version()
        except Exception:
            return False
    try:
        return bool(
            publication_parked_recheck_due(
                observed,
                item.parked_checked_at,
                item.parked_rules_version,
                current,
                recheck_interval_seconds,
            )
        )
    except Exception:
        return False


def current_scanner_rules_version() -> int | None:
    """Return the current scanner rules version, or None when unavailable."""

    try:
        from sase.core.agent_publication_recovery import (
            attachment_scanner_rules_version,
        )

        return attachment_scanner_rules_version()
    except Exception:
        return None


def park_agent_publications(
    project_key: str,
    parked_reasons: dict[tuple[str, str], str],
    *,
    now: float | None = None,
    rules_version: int | None = None,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Park withheld rows without charging attempts.

    Preserves ``parked_since`` across re-parks. Returns the resulting outbox.
    """

    if not parked_reasons:
        return list_agent_publications(project_key)
    observed = time.time() if now is None else now
    current_rules = (
        rules_version if rules_version is not None else current_scanner_rules_version()
    )
    selected = frozenset(parked_reasons)

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        updated: list[AgentPublicationOutboxItem] = []
        for item in items:
            if item.logical_key not in selected:
                updated.append(item)
                continue
            reason = parked_reasons[item.logical_key]
            parked_since = (
                item.parked_since if item.parked_since is not None else observed
            )
            updated.append(
                replace(
                    item,
                    last_error=reason,
                    parked_reason=reason,
                    parked_since=parked_since,
                    parked_checked_at=observed,
                    parked_rules_version=current_rules,
                    updated_at=observed,
                )
            )
        return tuple(updated)

    return mutate_publication_outbox(project_key, update)


@dataclass(frozen=True, slots=True)
class PublicationDrainBatchSelection:
    """One bounded retry selection made atomically with outbox revival."""

    active: tuple[AgentPublicationOutboxItem, ...]
    revived: tuple[AgentPublicationOutboxItem, ...]
    diagnostics: tuple[str, ...]

    @property
    def logical_keys(self) -> tuple[tuple[str, str], ...]:
        return tuple(item.logical_key for item in (*self.active, *self.revived))


def select_and_revive_agent_publications(
    project_key: str,
    *,
    limit: int,
    retry_retired: bool,
    retry_quarantined: bool,
    error_classes: Iterable[str] = (),
    exact_key: tuple[str, str] | None = None,
) -> PublicationDrainBatchSelection:
    """Select a bounded batch and revive only its stopped rows under one lock."""

    now = time.time()
    selection: PublicationDrainSelection | None = None

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        nonlocal selection
        selection = select_publication_drain(
            tuple(
                {
                    "global_agent": item.global_agent,
                    "primary_revision": item.primary_revision,
                    "terminal": item.terminal,
                    "quarantined": item.quarantined,
                    "last_error": item.last_error,
                    "terminal_reason": item.terminal_reason,
                    "created_at": item.created_at,
                }
                for item in items
            ),
            limit=limit,
            retry_retired=retry_retired,
            retry_quarantined=retry_quarantined,
            error_classes=tuple(error_classes),
            exact_key=exact_key,
        )
        revived_keys = {row.logical_key for row in selection.revive}
        return tuple(
            replace(
                item,
                attempts=0,
                last_error=None,
                quarantined=False,
                quarantined_at=None,
                terminal=False,
                terminal_reason=None,
                updated_at=now,
                parked_reason=None,
                parked_since=None,
                parked_checked_at=None,
                parked_rules_version=None,
            )
            if item.logical_key in revived_keys
            else item
            for item in items
        )

    updated = mutate_publication_outbox(project_key, update)
    if selection is None:
        raise RuntimeError("publication drain selection was not produced")
    items_by_key = {item.logical_key: item for item in updated}
    active = tuple(
        items_by_key[row.logical_key]
        for row in selection.active
        if row.logical_key in items_by_key
    )
    revived = tuple(
        items_by_key[row.logical_key]
        for row in selection.revive
        if row.logical_key in items_by_key
    )
    diagnostics = tuple(
        _bounded_selection_diagnostic(row, action="resumed") for row in selection.active
    ) + tuple(
        _bounded_selection_diagnostic(row, action="revived") for row in selection.revive
    )
    return PublicationDrainBatchSelection(active, revived, diagnostics)


def _bounded_selection_diagnostic(
    selected: PublicationRetrySelected,
    *,
    action: str,
) -> str:
    return (
        f"{action} {selected.prior_class} publication request "
        f"{selected.global_agent}@{selected.primary_revision[:12]} "
        f"({selected.error_class}): {selected.prior_failure}"
    )


def _merged_publication_scope(
    existing: AgentPublicationOutboxItem | None,
    incoming: AgentPublicationOutboxItem,
) -> str:
    """Keep revision scope when either the stored row or the incoming row has it."""

    if existing is None:
        return incoming.scope
    if (
        existing.scope == PUBLICATION_SCOPE_REVISION
        or incoming.scope == PUBLICATION_SCOPE_REVISION
    ):
        return PUBLICATION_SCOPE_REVISION
    return incoming.scope


def enqueue_agent_publication(
    item: AgentPublicationOutboxItem,
) -> AgentPublicationOutboxItem:
    """Insert or refresh *item* without duplicating its logical operation.

    Merging into the same logical key clears parked state: a fresh enqueue
    is a new publish attempt, not a continuation of a prior park.
    """

    validate_publication_item(item, item.project_key)
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
            terminal=existing.terminal if existing is not None else item.terminal,
            terminal_reason=(
                existing.terminal_reason
                if existing is not None
                else item.terminal_reason
            ),
            parked_reason=None,
            parked_since=None,
            parked_checked_at=None,
            parked_rules_version=None,
            commit_cwd=(
                existing.commit_cwd
                if existing is not None and existing.commit_cwd is not None
                else item.commit_cwd
            ),
            artifacts_dir=(
                existing.artifacts_dir
                if existing is not None and existing.artifacts_dir is not None
                else item.artifacts_dir
            ),
            run_id=(
                existing.run_id
                if existing is not None and existing.run_id is not None
                else item.run_id
            ),
            hood_digest=(
                existing.hood_digest
                if existing is not None and item.hood_digest == "pending"
                else item.hood_digest
            ),
            scope=_merged_publication_scope(existing, item),
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

    Any charged update clears parked state: a row that earns another attempt
    has been selected for work, so a prior park no longer applies.
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
            clear_parked = bool(increment_attempts)
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
                    parked_reason=None if clear_parked else item.parked_reason,
                    parked_since=None if clear_parked else item.parked_since,
                    parked_checked_at=None if clear_parked else item.parked_checked_at,
                    parked_rules_version=None
                    if clear_parked
                    else item.parked_rules_version,
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
                parked_reason=None,
                parked_since=None,
                parked_checked_at=None,
                parked_rules_version=None,
            )
            if item.quarantined and not item.terminal
            else item
            for item in items
        )

    return mutate_publication_outbox(project_key, update)


def revive_agent_publications(
    project_key: str,
    *,
    retry_retired: bool,
    retry_quarantined: bool,
) -> tuple[tuple[AgentPublicationOutboxItem, ...], tuple[str, ...]]:
    """Revive selected terminal rows once under the outbox lock.

    Selection and the resulting state transition come from the Rust policy.
    The transformation itself stays inside the existing locked atomic write.
    Active rows, other projects, and the Referenced By queue are untouched.
    """

    if not retry_retired and not retry_quarantined:
        return (), ()
    now = time.time()
    selected: list[PublicationRetrySelected] = []

    def update(
        items: tuple[AgentPublicationOutboxItem, ...],
    ) -> tuple[AgentPublicationOutboxItem, ...]:
        selected.extend(
            select_publication_retries(
                tuple(
                    {
                        "global_agent": item.global_agent,
                        "primary_revision": item.primary_revision,
                        "terminal": item.terminal,
                        "quarantined": item.quarantined,
                        "last_error": item.last_error,
                        "terminal_reason": item.terminal_reason,
                    }
                    for item in items
                ),
                retry_retired=retry_retired,
                retry_quarantined=retry_quarantined,
            )
        )
        chosen = {item.logical_key for item in selected}
        return tuple(
            replace(
                item,
                attempts=0,
                last_error=None,
                quarantined=False,
                quarantined_at=None,
                terminal=False,
                terminal_reason=None,
                updated_at=now,
                parked_reason=None,
                parked_since=None,
                parked_checked_at=None,
                parked_rules_version=None,
            )
            if item.logical_key in chosen
            else item
            for item in items
        )

    mutate_publication_outbox(project_key, update)
    return tuple(
        item
        for item in list_agent_publications(project_key)
        if item.logical_key in {row.logical_key for row in selected}
    ), _retry_diagnostics(selected)


def _retry_diagnostics(
    selected: list[PublicationRetrySelected],
) -> tuple[str, ...]:
    if not selected:
        return ()
    lines: list[str] = []
    for class_name, verb in (("retired", "retried"), ("quarantined", "retried")):
        matching = [item for item in selected if item.prior_class == class_name]
        if not matching:
            continue
        plural = "" if len(matching) == 1 else "s"
        lines.append(f"{verb} {len(matching)} {class_name} publication request{plural}")
        lines.extend(
            f"{verb} {class_name} publication request {item.global_agent}@"
            f"{item.primary_revision[:12]}: {item.prior_failure}"
            for item in matching
        )
    return tuple(lines)


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
    """Render stable diagnostics for stopped requests in *project_key*.

    A quarantined request is retryable and names the retry command; a retired
    request can never be published and names the drop command instead.
    """

    return tuple(
        publication_stopped_diagnostic(item)
        for item in list_agent_publications(project_key)
        if item.terminal or item.quarantined
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
    "PublicationDrainBatchSelection",
    "acknowledge_agent_publications",
    "clear_quarantined_agent_publications",
    "configured_publication_max_attempts",
    "current_scanner_rules_version",
    "drop_terminal_agent_publications",
    "enqueue_agent_publication",
    "park_agent_publications",
    "publication_is_parked_due",
    "publication_quarantine_diagnostics",
    "revive_agent_publications",
    "select_and_revive_agent_publications",
    "update_agent_publications",
]
