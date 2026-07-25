"""Formatting coverage for cached agents-sync outcomes."""

from sase.ace.tui.agents_sync_format import (
    cached_agents_result_line,
    summarize_cached_agents_results,
)
from sase.agents_sync.models import CachedIntegrationResult, CapturedIncomingHood


def test_owner_observed_cached_result_is_rendered_plainly() -> None:
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

    assert (
        cached_agents_result_line(result)
        == "Project: unknown-user.athena.crew — owner observed"
    )
    assert summarize_cached_agents_results((result,)) == "1 owner observed"
