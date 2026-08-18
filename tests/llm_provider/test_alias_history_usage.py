"""Tests for the frontend-neutral alias-history model-usage summarizer."""

from __future__ import annotations

from sase.llm_provider.alias_history_usage import summarize_alias_history_usage

from tests._alias_history_helpers import (
    make_group,
    make_pool_member,
    make_run,
    make_view,
)


def _summarize(runs: list, *, pool=(), groups=None):
    if groups is None:
        groups = [make_group("large", runs)]
    return summarize_alias_history_usage(make_view(groups), pool=pool)


def test_dedupes_same_artifact_dir_across_bucket_groups() -> None:
    shared = make_run(artifact_dir="/tmp/shared", model="opus")
    other = make_run(artifact_dir="/tmp/other", model="sonnet")
    summary = _summarize(
        [],
        groups=[
            make_group("research_a", [shared, other]),
            make_group(
                "research_b", [make_run(artifact_dir="/tmp/shared", model="opus")]
            ),
        ],
    )
    assert summary.counted_runs == 2
    assert summary.duplicate_runs == 1
    by_model = {row.model: row.count for row in summary.rows}
    assert by_model == {"opus": 1, "sonnet": 1}


def test_rank_order_is_count_then_unrecorded_then_label() -> None:
    runs = [
        make_run(artifact_dir="/tmp/s1", model="sonnet"),
        make_run(artifact_dir="/tmp/s2", model="sonnet"),
        make_run(artifact_dir="/tmp/h1", model="haiku"),
        make_run(artifact_dir="/tmp/h2", model="haiku"),
        make_run(artifact_dir="/tmp/o1", model="opus"),
        make_run(artifact_dir="/tmp/o2", model="opus"),
        make_run(artifact_dir="/tmp/o3", model="opus"),
        make_run(artifact_dir="/tmp/u1", model=None),
        make_run(artifact_dir="/tmp/u2", model=None),
    ]
    summary = _summarize(runs)
    assert [row.model for row in summary.rows] == ["opus", "haiku", "sonnet", None]
    assert summary.rows[-1].is_unrecorded is True
    assert [row.count for row in summary.rows] == [3, 2, 2, 2]


def test_zero_count_pool_members_are_present_and_last() -> None:
    runs = [
        make_run(artifact_dir="/tmp/1", model="sonnet", llm_provider="claude"),
        make_run(artifact_dir="/tmp/2", model="sonnet", llm_provider="claude"),
    ]
    pool = (
        make_pool_member("claude", "sonnet", effort="high"),
        make_pool_member("claude", "opus", effort="high"),
        make_pool_member("grok", "grok-4.6", effort="xhigh"),
    )
    summary = _summarize(runs, pool=pool)
    assert [row.model for row in summary.rows] == ["sonnet", "opus", "grok-4.6"]
    assert summary.rows[0].count == 2
    assert summary.rows[1].count == 0
    assert summary.rows[2].count == 0
    assert summary.rows[1].share_percent == 0
    assert summary.rows[2].in_pool is True


def test_off_pool_classification_for_observed_but_unconfigured_model() -> None:
    runs = [
        make_run(artifact_dir="/tmp/1", model="haiku", llm_provider="claude"),
        make_run(artifact_dir="/tmp/2", model="sonnet", llm_provider="claude"),
    ]
    pool = (make_pool_member("claude", "sonnet"),)
    summary = _summarize(runs, pool=pool)
    haiku = next(row for row in summary.rows if row.model == "haiku")
    sonnet = next(row for row in summary.rows if row.model == "sonnet")
    assert haiku.in_pool is False
    assert sonnet.in_pool is True
    assert haiku.is_unrecorded is False


def test_unrecorded_bucket_collects_runs_with_no_model() -> None:
    runs = [
        make_run(artifact_dir="/tmp/1", model=None),
        make_run(artifact_dir="/tmp/2", model="  "),
        make_run(artifact_dir="/tmp/3", model="opus"),
    ]
    summary = _summarize(runs)
    unrecorded = next(row for row in summary.rows if row.is_unrecorded)
    assert unrecorded.count == 2
    assert unrecorded.model is None
    assert unrecorded.provider is None


def test_percent_apportionment_sums_to_100_for_three_way_even_split() -> None:
    runs = [
        make_run(artifact_dir="/tmp/a", model="alpha"),
        make_run(artifact_dir="/tmp/b", model="bravo"),
        make_run(artifact_dir="/tmp/c", model="charlie"),
    ]
    summary = _summarize(runs)
    percents = [row.share_percent for row in summary.rows]
    assert sum(percents) == 100
    assert sorted(percents) == [33, 33, 34]


def test_percent_apportionment_sums_to_100_for_seven_model_split() -> None:
    runs = [
        make_run(artifact_dir=f"/tmp/{index}", model=f"m{index}") for index in range(7)
    ]
    summary = _summarize(runs)
    percents = [row.share_percent for row in summary.rows]
    assert sum(percents) == 100
    assert sorted(percents) == [14, 14, 14, 14, 14, 15, 15]


def test_single_effort_is_preserved_and_mixed_is_flagged() -> None:
    same = [
        make_run(artifact_dir="/tmp/1", model="opus", reasoning_effort="high"),
        make_run(artifact_dir="/tmp/2", model="opus", reasoning_effort="high"),
    ]
    mixed = [
        make_run(artifact_dir="/tmp/3", model="sonnet", reasoning_effort="high"),
        make_run(artifact_dir="/tmp/4", model="sonnet", reasoning_effort="low"),
    ]
    summary = _summarize(same + mixed)
    opus = next(row for row in summary.rows if row.model == "opus")
    sonnet = next(row for row in summary.rows if row.model == "sonnet")
    assert opus.effort == "high"
    assert opus.effort_is_mixed is False
    assert opus.effort_label == "high"
    assert sonnet.effort is None
    assert sonnet.effort_is_mixed is True
    assert sonnet.effort_label == "mixed"


def test_provider_unknown_fallback_matches_on_model_alone() -> None:
    runs = [
        make_run(artifact_dir="/tmp/1", model="sonnet", llm_provider="claude"),
    ]
    pool = (make_pool_member(None, "sonnet", effort="high"),)
    summary = _summarize(runs, pool=pool)
    assert len(summary.rows) == 1
    assert summary.rows[0].in_pool is True
    assert summary.rows[0].model == "sonnet"
    assert summary.pool_used == 1
    assert summary.pool_total == 1


def test_run_without_provider_matches_configured_member_on_model() -> None:
    runs = [
        make_run(artifact_dir="/tmp/1", model="sonnet", llm_provider=None),
    ]
    pool = (make_pool_member("claude", "sonnet"),)
    summary = _summarize(runs, pool=pool)
    assert summary.rows[0].in_pool is True
    assert summary.pool_used == 1


def test_empty_view_has_zero_counts_and_optional_unused_pool_rows() -> None:
    empty = _summarize([])
    assert empty.counted_runs == 0
    assert empty.duplicate_runs == 0
    assert empty.rows == ()
    assert empty.pool_total == 0
    assert empty.pool_used == 0

    with_pool = _summarize([], pool=(make_pool_member("claude", "opus"),))
    assert with_pool.counted_runs == 0
    assert with_pool.pool_total == 1
    assert with_pool.pool_used == 0
    assert with_pool.rows[0].count == 0
    assert with_pool.rows[0].share_percent == 0


def test_pool_used_and_pool_total() -> None:
    runs = [make_run(artifact_dir="/tmp/1", model="sonnet", llm_provider="claude")]
    pool = (
        make_pool_member("claude", "sonnet"),
        make_pool_member("claude", "opus"),
        make_pool_member("grok", "grok-4.6"),
    )
    summary = _summarize(runs, pool=pool)
    assert summary.pool_total == 3
    assert summary.pool_used == 1


def test_weights_do_not_affect_counts() -> None:
    runs = [
        make_run(artifact_dir="/tmp/1", model="opus", llm_provider="claude"),
        make_run(artifact_dir="/tmp/2", model="opus", llm_provider="claude"),
    ]
    pool = (make_pool_member("claude", "opus", weight=7),)
    summary = _summarize(runs, pool=pool)
    assert summary.rows[0].count == 2
    assert summary.counted_runs == 2


def test_display_casing_uses_first_observed_then_configured_spelling() -> None:
    runs = [
        make_run(
            artifact_dir="/tmp/1",
            model="Opus",
            llm_provider="Claude",
        ),
        make_run(
            artifact_dir="/tmp/2",
            model="opus",
            llm_provider="claude",
        ),
    ]
    pool = (
        make_pool_member("Claude", "Opus"),
        make_pool_member("Grok", "Grok-4.6"),
    )
    summary = _summarize(runs, pool=pool)
    assert summary.rows[0].provider == "Claude"
    assert summary.rows[0].model == "Opus"
    unused = next(row for row in summary.rows if row.count == 0)
    assert unused.provider == "Grok"
    assert unused.model == "Grok-4.6"


def test_status_rollup_is_per_model() -> None:
    runs = [
        make_run(artifact_dir="/tmp/1", model="opus", rollup_status="done"),
        make_run(
            artifact_dir="/tmp/2",
            model="opus",
            rollup_status="failed",
            status="failed",
        ),
        make_run(
            artifact_dir="/tmp/3",
            model="opus",
            rollup_status="running",
            status="running",
        ),
    ]
    summary = _summarize(runs)
    row = summary.rows[0]
    assert row.done == 1
    assert row.failed == 1
    assert row.running == 1


def test_no_effort_suffix_when_no_recorded_effort() -> None:
    runs = [make_run(artifact_dir="/tmp/1", model="opus", reasoning_effort=None)]
    summary = _summarize(runs)
    assert summary.rows[0].effort is None
    assert summary.rows[0].effort_is_mixed is False
    assert summary.rows[0].effort_label is None
