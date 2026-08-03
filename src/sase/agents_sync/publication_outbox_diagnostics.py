"""Operator-facing diagnostics for queued publication requests."""

from __future__ import annotations

from sase.agents_sync.publication_outbox_models import SidecarPublicationRequest

PUBLICATION_RETRY_COMMAND = "sase agent sync --retry-quarantined"
PUBLICATION_DROP_COMMAND = "sase agent sync --drop-retired"


def publication_request_subject(item: SidecarPublicationRequest) -> str:
    """Return a concise, stable label for one typed publication request."""

    if item.kind == "agent_hood":
        return f"{item.global_agent}@{item.primary_revision[:12]}"
    if item.kind == "bead_pages":
        suffix = f"@{item.primary_revision[:12]}" if item.primary_revision else ""
        return f"bead lineage {item.lineage_root}{suffix}"
    if item.kind == "plan_header":
        return f"plan {item.plan_ref}@{item.primary_revision[:12]}"
    return f"{item.sidecar_kind} sidecar for {item.project}"


def publication_status_diagnostic(item: SidecarPublicationRequest) -> str:
    """Render the current status of one publication request."""

    if item.terminal or item.quarantined:
        return publication_stopped_diagnostic(item)

    subject = f"publication request {publication_request_subject(item)}"
    if item.attempts:
        message = f"{subject} queued for retry after {item.attempts} attempt(s)"
    else:
        message = f"{subject} queued for the publications lane"
    if item.last_error:
        message = f"{message}: {item.last_error}"
    return (
        f"{message}; run `sase axe chop run sidecar_publication -L publications` "
        "to drain now"
    )


def publication_stopped_diagnostic(item: SidecarPublicationRequest) -> str:
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
    "publication_status_diagnostic",
    "publication_stopped_diagnostic",
]
