"""Drain queued Referenced By write-back requests."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.git import GitRunner
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.referenced_by_events import (
    convert_fenced_referenced_by_backlog,
    legacy_referenced_by_writes_fenced,
)
from sase.agents_sync.referenced_by_outbox import (
    ReferencedByOutboxItem,
    acknowledge_referenced_by_requests,
    configured_publication_max_attempts,
    list_referenced_by_requests,
    update_referenced_by_requests,
)
from sase.sdd.referenced_by_refresh import refresh_referenced_by

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


def drain_referenced_by_requests(
    target: ProjectTarget,
    *,
    git_runner: GitRunner,
) -> tuple[str, ...]:
    """Drain active referenced-by requests for one project target."""

    del git_runner  # Store helpers own their git boundary today.
    if legacy_referenced_by_writes_fenced(target):
        return convert_fenced_referenced_by_backlog(target)
    requests = list_referenced_by_requests(
        target.project_key,
        include_quarantined=False,
    )
    if not requests:
        return ()
    try:
        store = _resolve_store(target)
    except PublicationDrainTimedOut:
        raise
    except Exception as exc:
        _record_failure(target, requests, f"could not resolve SDD store: {exc}")
        return (f"referenced-by drain failed: could not resolve SDD store: {exc}",)

    diagnostics: list[str] = []
    by_role: dict[str, list[ReferencedByOutboxItem]] = defaultdict(list)
    for item in requests:
        by_role[item.sidecar_role].append(item)
    for role, role_requests in sorted(
        by_role.items(),
        key=lambda item: (item[0] == "agents", item[0]),
    ):
        try:
            report = refresh_referenced_by(
                store,
                role=role,
                requests=tuple(role_requests),
                write=True,
            )
        except PublicationDrainTimedOut:
            raise
        except Exception as exc:  # noqa: BLE001 - charge so a fenced raise quarantines.
            error = str(exc) or type(exc).__name__
            _record_failure(target, role_requests, error)
            diagnostics.append(f"referenced-by {role} refresh failed: {error}")
            continue
        if report.ok:
            acknowledge_referenced_by_requests(
                target.project_key,
                (item.logical_key for item in role_requests),
            )
            continue
        error = "; ".join(issue.message for issue in report.errors) or "unknown error"
        update_referenced_by_requests(
            target.project_key,
            (item.logical_key for item in role_requests),
            error=error,
            increment_attempts=True,
            quarantine_threshold=configured_publication_max_attempts(),
        )
        diagnostics.append(f"referenced-by {role} refresh failed: {error}")
    return tuple(diagnostics)


def _record_failure(
    target: ProjectTarget,
    requests: Iterable[ReferencedByOutboxItem],
    error: str,
) -> None:
    update_referenced_by_requests(
        target.project_key,
        (item.logical_key for item in requests),
        error=error,
        increment_attempts=True,
        quarantine_threshold=configured_publication_max_attempts(),
    )


def _resolve_store(target: ProjectTarget) -> SddStore:
    from sase.sdd.artifact_link_store import resolve_machine_artifact_link_store

    link_store = resolve_machine_artifact_link_store(
        target.project_key, target.primary_checkout
    )
    assert link_store.sdd_store is not None
    return link_store.sdd_store


__all__ = ["drain_referenced_by_requests"]
