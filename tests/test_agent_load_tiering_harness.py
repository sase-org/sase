"""Fast smoke coverage for the ``sase-zu`` load-tiering oracle."""

from __future__ import annotations

from pathlib import Path

from tests.perf.agent_load_tiering_harness import (
    AgentLoadTieringOracle,
    QUERY_BATTERY,
    build_synthetic_agent_archive,
)


def test_load_tiering_query_battery_has_no_missing_rows_within_tier1_window(
    tmp_path: Path,
) -> None:
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=72)
    oracle = AgentLoadTieringOracle(fixture)

    for case in QUERY_BATTERY:
        result = oracle.evaluate(case.query, requested_limit=400)

        assert bool(result.query_error) is case.expect_query_error, case.query
        assert result.diff_for("index_bounded").missing == (), case.query
        assert result.diff_for("index_bounded").visible_extra == (), case.query
        assert result.diff_for("index_full_history").missing == (), case.query
        assert result.diff_for("index_full_history").visible_extra == (), case.query


def test_load_tiering_oracle_reports_under_selecting_candidate_filter_on_index_paths(
    tmp_path: Path,
) -> None:
    fixture = build_synthetic_agent_archive(tmp_path / "fixture", artifact_count=48)
    oracle = AgentLoadTieringOracle(fixture)

    result = oracle.evaluate(
        "provider:codex",
        requested_limit=400,
        candidate_filter_override={
            "kind": "equals",
            "field": "provider",
            "value": "provider-that-does-not-exist",
        },
    )

    bounded_diff = result.diff_for("index_bounded")
    assert bounded_diff.missing
    full_history_diff = result.diff_for("index_full_history")
    assert full_history_diff.missing == bounded_diff.missing
