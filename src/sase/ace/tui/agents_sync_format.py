"""Pure formatting helpers for ACE agents-repository sync surfaces."""

from __future__ import annotations

from collections.abc import Sequence

from sase.agents_sync.models import (
    CachedIntegrationResult,
    CapturedIncomingHood,
    ProjectSyncStatus,
    SyncOutcome,
)


def agents_sync_status_needs_attention(status: ProjectSyncStatus) -> bool:
    """Return whether cached incoming hoods are waiting to be imported."""
    return status.pending_foreign_count > 0


def captured_agent_hood_label(item: CapturedIncomingHood) -> str:
    """Render the explicit source owner and hood without external lookups."""
    owner = (
        f"{item.source_username}.{item.source_machine}"
        if item.source_username
        else f"unknown-user.{item.source_machine}"
    )
    return f"{owner}.{item.top_hood}"


def _agents_sync_outcome_changed(outcome: SyncOutcome) -> bool:
    """Return whether a successful outcome changed shared agent data."""
    return bool(
        outcome.integrated
        or outcome.refreshed
        or outcome.exported
        or outcome.export_refreshed
        or outcome.hoods_published
        or outcome.hoods_refreshed
        or outcome.committed
        or outcome.pushed
    )


def summarize_agents_sync_outcomes(outcomes: Sequence[SyncOutcome]) -> str:
    """Return compact ordered counts for task and comprehensive summaries."""
    counts = {"synchronized": 0, "current": 0, "skipped": 0, "failed": 0}
    for outcome in outcomes:
        if outcome.error:
            counts["failed"] += 1
        elif outcome.skip_reason:
            counts["skipped"] += 1
        elif _agents_sync_outcome_changed(outcome):
            counts["synchronized"] += 1
        else:
            counts["current"] += 1
    parts = [f"{count} {label}" for label, count in counts.items() if count]
    return ", ".join(parts) if parts else "no enabled repositories"


def summarize_cached_agents_results(
    results: Sequence[CachedIntegrationResult],
) -> str:
    """Return compact disposition counts for cached inbound integration."""
    counts: dict[str, int] = {}
    for result in results:
        label = result.disposition.replace("_", " ")
        counts[label] = counts.get(label, 0) + 1
    parts = [f"{count} {label}" for label, count in counts.items()]
    return ", ".join(parts) if parts else "no cached agent hoods"


__all__ = [
    "agents_sync_status_needs_attention",
    "captured_agent_hood_label",
    "summarize_cached_agents_results",
    "summarize_agents_sync_outcomes",
]
