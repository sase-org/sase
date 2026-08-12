"""Drain queued Referenced By write-back requests."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING

from sase.agents_sync.git import GitRunner
from sase.agents_sync.models import ProjectTarget
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
    requests = list_referenced_by_requests(
        target.project_key,
        include_quarantined=False,
    )
    if not requests:
        return ()
    try:
        store = _resolve_store(target)
    except Exception as exc:
        _record_failure(target, requests, f"could not resolve SDD store: {exc}")
        return (f"referenced-by drain failed: could not resolve SDD store: {exc}",)

    diagnostics: list[str] = []
    by_role: dict[str, list[ReferencedByOutboxItem]] = defaultdict(list)
    for item in requests:
        by_role[item.sidecar_role].append(item)
    for role, role_requests in sorted(by_role.items()):
        report = refresh_referenced_by(
            store,
            role=role,
            requests=tuple(role_requests),
            write=True,
        )
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
    from sase.sdd.plan_refs import workspace_context_for_plan_resolution
    from sase.sdd.store import resolve_sdd_store

    workspace, number = workspace_context_for_plan_resolution(target.primary_checkout)
    return resolve_sdd_store(workspace, number)


__all__ = ["drain_referenced_by_requests"]
