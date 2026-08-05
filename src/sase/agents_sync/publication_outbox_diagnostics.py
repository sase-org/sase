"""Operator-facing diagnostics for queued publication requests."""

from __future__ import annotations

from sase.agents_sync.publication_outbox_models import AgentPublicationOutboxItem

PUBLICATION_RETRY_COMMAND = "sase agent sync --retry-quarantined"
PUBLICATION_DROP_COMMAND = "sase agent sync --drop-retired"


def publication_request_subject(item: AgentPublicationOutboxItem) -> str:
    """Return a concise, stable label for one agent-hood publication request."""

    return f"{item.global_agent}@{item.primary_revision[:12]}"


def publication_stopped_diagnostic(item: AgentPublicationOutboxItem) -> str:
    """Render one quarantined or retired request with accurate remediation."""

    subject = f"publication request {publication_request_subject(item)}"
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
    "PUBLICATION_DROP_COMMAND",
    "PUBLICATION_RETRY_COMMAND",
    "publication_request_subject",
    "publication_stopped_diagnostic",
]
