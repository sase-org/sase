"""Deep check reporting leftover locally materialized agents-sync import state."""

from __future__ import annotations

from sase.agents_sync.purge_local_state import purge_local_import_state
from sase.diagnostics import CheckStatus, DiagnosticCheck


def check_local_import_state() -> DiagnosticCheck:
    """Report whether any locally materialized import state remains."""
    outcome = purge_local_import_state(apply=False)
    counts = {
        "artifacts": len(outcome.artifact_dirs),
        "chat_files": len(outcome.chat_files),
        "bundles": len(outcome.bundle_files),
        "dismissed_identities": len(outcome.dismissed_identities),
        "import_dirs": len(outcome.import_dirs),
        "cache_dirs": len(outcome.cache_dirs),
        "receipt_files": len(outcome.receipt_files),
    }
    status: CheckStatus = "OK" if outcome.is_empty else "WARN"
    if outcome.is_empty:
        summary = "no locally materialized agents-sync import state found"
    else:
        nonzero = {key: value for key, value in counts.items() if value}
        summary = "leftover imported local state: " + ", ".join(
            f"{key}={value}" for key, value in nonzero.items()
        )
    details = tuple(f"{key}: {value}" for key, value in counts.items() if value)
    next_steps: tuple[str, ...] = ()
    if not outcome.is_empty:
        next_steps = (
            "Preview with `sase agent names purge-local-state`.",
            "Apply with `sase agent names purge-local-state --apply`.",
        )
    return DiagnosticCheck(
        id="state.imported_local_state",
        group="state",
        status=status,
        title="Imported local state",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={**counts, "is_empty": outcome.is_empty},
    )


__all__ = ["check_local_import_state"]
