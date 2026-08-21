"""Formatting coverage for cached agents-sync summaries."""

from sase.ace.tui.agents_sync_format import (
    agents_sync_outcome_line,
    cached_agents_result_line,
    summarize_cached_agents_results,
)
from sase.agents_sync.models import (
    CachedIntegrationResult,
    CapturedIncomingHood,
    SyncOutcome,
)


def test_owner_observed_cached_result_is_summarized_plainly() -> None:
    captured = CapturedIncomingHood(
        project_key="proj",
        project="Project",
        fetched_ref="refs/remotes/origin/main",
        fetched_sha="a" * 40,
        cache_id="b" * 64,
        format_version=1,
        source_owner_kind="username_unknown_v1",
        source_username=None,
        source_machine="athena",
        top_hood="crew",
        hood_digest="c" * 64,
        run_count=2,
        family_count=1,
        cache_created_at=1.0,
    )
    result = CachedIntegrationResult(
        captured,
        "owner_observed",
        unchanged=2,
    )

    assert summarize_cached_agents_results((result,)) == "1 owner observed"


def test_agents_sync_outcome_line_reports_failure_and_sync_details() -> None:
    failed = SyncOutcome("alpha", "Alpha", error="push failed")
    synced = SyncOutcome(
        "beta", "Beta", pulled=True, hoods_published=2, runs_published=3
    )

    assert agents_sync_outcome_line(failed) == "Alpha: failed — push failed"
    assert "Beta: synchronized" in agents_sync_outcome_line(synced)
    assert "pulled" in agents_sync_outcome_line(synced)


def test_cached_agents_result_line_includes_disposition_and_counts() -> None:
    captured = CapturedIncomingHood(
        project_key="proj",
        project="Project",
        fetched_ref="refs/remotes/origin/main",
        fetched_sha="a" * 40,
        cache_id="b" * 64,
        format_version=2,
        source_owner_kind="exact",
        source_username="alice",
        source_machine="zeus",
        top_hood="crew",
        hood_digest="c" * 64,
        run_count=2,
        family_count=1,
        cache_created_at=1.0,
    )
    result = CachedIntegrationResult(
        captured,
        "applied",
        hoods_imported=1,
        runs_imported=2,
        families_imported=1,
    )

    line = cached_agents_result_line(result)
    assert line.startswith("Project: alice.zeus.crew — applied")
    assert "1 hood" in line
    assert "2 runs" in line
