"""Formatting coverage for agents-sidecar publication summaries."""

from sase.ace.tui.agents_sync_format import (
    agents_sync_outcome_line,
    summarize_agents_sync_outcomes,
)
from sase.agents_sync.models import SyncOutcome


def test_agents_sync_outcome_line_reports_failure_and_sync_details() -> None:
    failed = SyncOutcome("alpha", "Alpha", error="push failed")
    synced = SyncOutcome(
        "beta", "Beta", pulled=True, hoods_published=2, runs_published=3
    )

    assert agents_sync_outcome_line(failed) == "Alpha: failed — push failed"
    assert "Beta: synchronized" in agents_sync_outcome_line(synced)
    assert "pulled" in agents_sync_outcome_line(synced)


def test_summarize_agents_sync_outcomes_counts_states() -> None:
    outcomes = (
        SyncOutcome("alpha", "Alpha", pulled=True, hoods_published=1),
        SyncOutcome("beta", "Beta"),
        SyncOutcome("gamma", "Gamma", skip_reason="disabled"),
        SyncOutcome("delta", "Delta", error="push failed"),
    )

    assert (
        summarize_agents_sync_outcomes(outcomes)
        == "1 synchronized, 1 current, 1 skipped, 1 failed"
    )
