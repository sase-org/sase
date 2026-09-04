"""Pure formatting helpers for ACE agents-repository sync surfaces."""

from __future__ import annotations

from collections.abc import Sequence

from sase.agents_sync.models import SyncOutcome


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


def agents_sync_outcome_line(outcome: SyncOutcome) -> str:
    """Render one complete task-log line for a project outcome."""
    if outcome.error:
        return f"{outcome.project}: failed — {outcome.error}"
    if outcome.skip_reason:
        return f"{outcome.project}: skipped — {outcome.skip_reason}"

    details: list[str] = []
    if outcome.pulled:
        details.append("pulled")
    imported = outcome.integrated + outcome.refreshed
    if imported:
        details.append(f"imported {imported}")
    exported = outcome.exported + outcome.export_refreshed
    if exported:
        details.append(f"exported {exported} legacy bundles")
    hoods = outcome.hoods_published + outcome.hoods_refreshed
    if hoods:
        details.append(f"published {hoods} hoods / {outcome.runs_published} runs")
    if outcome.committed:
        details.append("committed")
    if outcome.pushed:
        details.append("pushed")
    if outcome.push_attempts > 1:
        details.append(f"{outcome.push_attempts} push attempts")
    details.extend(outcome.diagnostics)
    state = "synchronized" if _agents_sync_outcome_changed(outcome) else "current"
    return f"{outcome.project}: {state}" + (
        f" — {', '.join(details)}" if details else ""
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


__all__ = [
    "agents_sync_outcome_line",
    "summarize_agents_sync_outcomes",
]
