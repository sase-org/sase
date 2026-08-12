"""Operator-facing diagnostics for queued Referenced By requests."""

from __future__ import annotations

from sase.agents_sync.publication_outbox_diagnostics import (
    PUBLICATION_DROP_COMMAND,
    PUBLICATION_RETRY_COMMAND,
)
from sase.agents_sync.referenced_by_outbox_models import ReferencedByOutboxItem


def referenced_by_request_subject(item: ReferencedByOutboxItem) -> str:
    """Return a concise, stable label for one back-reference request."""

    return (
        f"{item.global_agent}@{item.primary_revision[:12]} -> "
        f"{item.sidecar_role}:{item.repo_relpath}"
    )


def referenced_by_stopped_diagnostic(item: ReferencedByOutboxItem) -> str:
    """Render one quarantined or retired request with accurate remediation."""

    subject = f"referenced-by request {referenced_by_request_subject(item)}"
    if item.terminal:
        reason = item.terminal_reason or item.last_error or "unknown reason"
        return (
            f"{subject} retired as unpublishable: {reason}; run "
            f"`{PUBLICATION_DROP_COMMAND}` to drop it"
        )
    return (
        f"{subject} quarantined after {item.attempts} attempts: "
        f"{item.last_error or 'unknown error'}; run "
        f"`{PUBLICATION_RETRY_COMMAND}` to retry"
    )


__all__ = [
    "referenced_by_request_subject",
    "referenced_by_stopped_diagnostic",
]
