"""Operator-facing diagnostics for queued publication requests."""

from __future__ import annotations

from sase.agents_sync.publication_outbox_models import AgentPublicationOutboxItem

PUBLICATION_RETRY_COMMAND = "sase agent sync --retry-quarantined"
PUBLICATION_DROP_COMMAND = "sase agent sync --drop-retired"

# (needle, error class) pairs, first match wins. Classes feed the doctor
# ``last_error_histogram`` and the drain-timing JSONL ``error_class`` field so
# both surfaces report the same failure taxonomy.
_ERROR_CLASS_NEEDLES: tuple[tuple[str, str], ...] = (
    ("did not complete within", "timeout"),
    ("agents sync lock is busy", "lock_busy"),
    ("agents sync clone lock is busy", "lock_busy"),
    ("index.lock", "index_lock"),
    ("unstaged changes", "unstaged_changes"),
    ("would be overwritten", "unstaged_changes"),
    ("rebase", "rebase_conflict"),
    ("conflict", "rebase_conflict"),
    ("manifest", "manifest_mismatch"),
    ("exceeds the byte limit", "manifest_mismatch"),
)


def classify_publication_error(error: str | None) -> str:
    """Return the stable failure class for one publication error message."""

    if not error:
        return "unknown"
    lowered = error.lower()
    for needle, error_class in _ERROR_CLASS_NEEDLES:
        if needle in lowered:
            return error_class
    return "other"


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
    "classify_publication_error",
    "publication_request_subject",
    "publication_stopped_diagnostic",
]
