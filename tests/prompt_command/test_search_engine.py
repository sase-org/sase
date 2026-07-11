"""Tests for the deterministic prompt-search engine: match, filter, rank, limit."""

from __future__ import annotations

import pytest

from sase.prompt.search.engine import EmptyPromptQueryError, search_prompts
from sase.prompt.search.model import (
    PromptHit,
    PromptSearchResult,
    PromptSource,
)


def _sdd(
    locator: str,
    *,
    text: str = "",
    title: str | None = None,
    date: str = "260101_000000",
    path: str | None = None,
    plan: str | None = None,
    tags: tuple[str, ...] = (),
) -> PromptHit:
    return PromptHit(
        source=PromptSource.SDD,
        id=locator,
        text=text,
        title=title if title is not None else locator,
        date=date,
        text_sha256=f"sha-{locator}",
        path=path if path is not None else f"sdd/prompts/202601/{locator}.md",
        plan=plan,
        tags=tags,
        cancelled=None,
    )


def _local(
    locator: str,
    *,
    text: str = "",
    title: str | None = None,
    date: str = "260101_000000",
    tags: tuple[str, ...] = (),
    cancelled: bool = False,
) -> PromptHit:
    return PromptHit(
        source=PromptSource.LOCAL,
        id=locator,
        text=text,
        title=title if title is not None else locator,
        date=date,
        text_sha256=f"sha-{locator}",
        path=None,
        plan=None,
        tags=tags,
        cancelled=cancelled,
    )


def _ids(result: PromptSearchResult) -> list[str]:
    return [match.hit.id for match in result.matches]


# ---------------------------------------------------------------------------
# Matching — per field, recorded matched_fields, case-insensitivity
# ---------------------------------------------------------------------------


def _distinct_field_hit() -> PromptHit:
    """An SDD hit whose query-able fields share no substrings."""
    return _sdd(
        "gamma_id",
        title="alpha title",
        text="beta body",
        path="sdd/prompts/202601/delta_path.md",
        plan="sdd/plans/202601/epsilon_plan.md",
        tags=("zeta",),
    )


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("alpha", "title"),
        ("beta", "body"),
        ("gamma", "id"),
        ("delta", "path"),
        ("epsilon", "plan"),
        ("zeta", "tags"),
    ],
)
def test_match_records_each_field(query: str, field: str) -> None:
    result = search_prompts(query, [_distinct_field_hit()])
    assert result.count == 1
    assert result.matches[0].matched_fields == (field,)


def test_matched_fields_use_stable_order() -> None:
    # The query appears in several fields; matched_fields follows the fixed
    # field order (title, body, id, path, plan, tags) regardless of input.
    hit = _sdd(
        "auth_id",
        title="auth title",
        text="auth body",
        path="sdd/prompts/202601/auth_id.md",
        plan="sdd/plans/202601/auth.md",
        tags=("auth",),
    )
    result = search_prompts("auth", [hit])
    assert result.matches[0].matched_fields == (
        "title",
        "body",
        "id",
        "path",
        "plan",
        "tags",
    )


def test_match_is_case_insensitive() -> None:
    hit = _sdd("x", title="Refactor the TUI Renderer", text="body")
    assert search_prompts("tui", [hit]).count == 1
    assert search_prompts("REND", [hit]).count == 1


def test_no_match_when_query_absent_everywhere() -> None:
    result = search_prompts("absent", [_distinct_field_hit()])
    assert result.count == 0
    assert result.total == 0
    assert result.query == "absent"
    assert result.count_for(PromptSource.SDD) == 0
    assert result.count_for(PromptSource.LOCAL) == 0


def test_none_path_and_plan_do_not_crash_matching() -> None:
    # Local hits have path/plan == None; matching must skip them cleanly.
    hit = _local("ph_a", text="something about widgets")
    result = search_prompts("widgets", [hit])
    assert result.matches[0].matched_fields == ("body",)


# ---------------------------------------------------------------------------
# Both sources, ranking
# ---------------------------------------------------------------------------


def test_finds_matches_in_both_sources_with_counts() -> None:
    hits = [
        _sdd("s1", text="shared topic"),
        _local("ph_1", text="shared topic too"),
    ]
    result = search_prompts("shared", hits)
    assert result.total == 2
    assert result.count_for(PromptSource.SDD) == 1
    assert result.count_for(PromptSource.LOCAL) == 1


def test_sdd_ranks_before_local_even_when_local_is_newer() -> None:
    # Source priority dominates recency: SDD wins despite the older date.
    hits = [
        _local("ph_new", title="shared", date="260601_000000"),
        _sdd("s_old", title="shared", date="260101_000000"),
    ]
    result = search_prompts("shared", hits)
    assert _ids(result) == ["s_old", "ph_new"]


def test_match_tier_beats_recency_within_a_source() -> None:
    # A title (strong-field) hit outranks a newer body-only hit.
    body_only_newer = _sdd("body_hit", title="aaa", text="shared", date="260301_000000")
    title_older = _sdd(
        "title_hit", title="shared headline", text="bbb", date="260101_000000"
    )
    result = search_prompts("shared", [body_only_newer, title_older])
    assert _ids(result) == ["title_hit", "body_hit"]


def test_recency_orders_within_same_source_and_tier() -> None:
    older = _sdd("older", title="shared", date="260101_000000")
    newer = _sdd("newer", title="shared", date="260301_000000")
    result = search_prompts("shared", [older, newer])
    assert _ids(result) == ["newer", "older"]


def test_stable_tiebreak_and_determinism() -> None:
    # Same source/tier/date: ordered by (path, id); stable across input order.
    e = _sdd("e_id", title="shared", path="sdd/prompts/202601/e.md")
    f = _sdd("f_id", title="shared", path="sdd/prompts/202601/f.md")
    forward = _ids(search_prompts("shared", [e, f]))
    reversed_ = _ids(search_prompts("shared", [f, e]))
    assert forward == ["e_id", "f_id"]
    assert forward == reversed_


def test_undated_hits_rank_last() -> None:
    dated = _sdd("dated", title="shared", date="260101_000000")
    undated = _sdd("undated", title="shared", date="")
    result = search_prompts("shared", [undated, dated])
    assert _ids(result) == ["dated", "undated"]


# ---------------------------------------------------------------------------
# Filters (AND): source, date, tag, cancelled
# ---------------------------------------------------------------------------


def test_source_filter_excludes_other_source() -> None:
    hits = [_sdd("s1", text="topic"), _local("ph_1", text="topic")]
    result = search_prompts("topic", hits, sources=[PromptSource.SDD])
    assert _ids(result) == ["s1"]
    assert result.count_for(PromptSource.LOCAL) == 0


def test_empty_sources_means_all() -> None:
    hits = [_sdd("s1", text="topic"), _local("ph_1", text="topic")]
    assert search_prompts("topic", hits, sources=[]).total == 2


def test_date_range_filters_inclusively() -> None:
    hits = [
        _sdd("jan", text="topic", date="260101_000000"),
        _sdd("mar", text="topic", date="260301_000000"),
        _sdd("jun", text="topic", date="260601_000000"),
    ]
    after = search_prompts("topic", hits, after="260301_000000")
    assert set(_ids(after)) == {"mar", "jun"}  # boundary is inclusive
    before = search_prompts("topic", hits, before="260301_000000")
    assert set(_ids(before)) == {"jan", "mar"}
    window = search_prompts(
        "topic", hits, after="260201_000000", before="260401_000000"
    )
    assert _ids(window) == ["mar"]


def test_tag_filter_ors_across_repeats() -> None:
    hits = [
        _sdd("review_hit", text="topic", tags=("review",)),
        _sdd("auth_hit", text="topic", tags=("auth",)),
        _sdd("docs_hit", text="topic", tags=("docs",)),
    ]
    only_review = search_prompts("topic", hits, tags=["review"])
    assert _ids(only_review) == ["review_hit"]
    either = search_prompts("topic", hits, tags=["review", "auth"])
    assert set(_ids(either)) == {"review_hit", "auth_hit"}


def test_tag_filter_is_case_insensitive_and_sigil_tolerant() -> None:
    hits = [_sdd("h", text="topic", tags=("Review",))]
    assert search_prompts("topic", hits, tags=["review"]).count == 1
    assert search_prompts("topic", hits, tags=["#REVIEW"]).count == 1


def test_tag_filter_excludes_query_match_without_the_tag() -> None:
    # A hit that matches the query is still dropped when it lacks the tag.
    hits = [_sdd("h", text="topic about review", tags=("docs",))]
    assert search_prompts("topic", hits, tags=["review"]).count == 0


def test_cancelled_only_restricts_local_but_not_sdd() -> None:
    hits = [
        _local("ph_cancel", text="topic", cancelled=True),
        _local("ph_live", text="topic", cancelled=False),
        _sdd("s1", text="topic"),  # SDD has no cancelled state
    ]
    result = search_prompts("topic", hits, cancelled_only=True)
    assert set(_ids(result)) == {"ph_cancel", "s1"}


def test_filters_and_together() -> None:
    hits = [
        # matches query + tag + source + date window
        _sdd("keep", text="topic", tags=("review",), date="260301_000000"),
        # right tag, wrong date
        _sdd("old", text="topic", tags=("review",), date="260101_000000"),
        # right date, wrong tag
        _sdd("untagged", text="topic", tags=("docs",), date="260301_000000"),
        # right everything but wrong source
        _local("ph_x", text="topic", tags=("review",), date="260301_000000"),
    ]
    result = search_prompts(
        "topic",
        hits,
        sources=[PromptSource.SDD],
        tags=["review"],
        after="260201_000000",
    )
    assert _ids(result) == ["keep"]


# ---------------------------------------------------------------------------
# Limit, total, counts
# ---------------------------------------------------------------------------


def test_limit_caps_shown_but_reports_full_total_and_counts() -> None:
    hits = [
        _sdd("s1", title="shared", date="260105_000000"),
        _sdd("s2", title="shared", date="260104_000000"),
        _local("ph_1", title="shared", date="260103_000000"),
        _local("ph_2", title="shared", date="260102_000000"),
        _local("ph_3", title="shared", date="260101_000000"),
    ]
    result = search_prompts("shared", hits, limit=2)
    assert result.count == 2
    assert result.total == 5
    assert result.count_for(PromptSource.SDD) == 2
    assert result.count_for(PromptSource.LOCAL) == 3
    # The two shown are the top-ranked (both SDD, newer first).
    assert _ids(result) == ["s1", "s2"]


def test_limit_zero_is_unlimited() -> None:
    hits = [_sdd(f"s{i}", title="shared", date=f"26010{i}_000000") for i in range(1, 6)]
    assert search_prompts("shared", hits, limit=0).count == 5
    assert search_prompts("shared", hits, limit=-1).count == 5  # negatives too


def test_counts_always_carry_both_sources() -> None:
    result = search_prompts("shared", [_sdd("s1", title="shared")])
    assert result.count_for(PromptSource.SDD) == 1
    assert result.count_for(PromptSource.LOCAL) == 0


# ---------------------------------------------------------------------------
# Query validation, result envelope
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["", "   ", "\t\n"])
def test_empty_or_whitespace_query_raises(query: str) -> None:
    with pytest.raises(EmptyPromptQueryError):
        search_prompts(query, [_sdd("s1", text="anything")])


def test_query_is_stripped_in_result() -> None:
    result = search_prompts("  shared  ", [_sdd("s1", title="shared")])
    assert result.query == "shared"
    assert result.count == 1


def test_repeated_calls_are_deterministic() -> None:
    hits = [
        _sdd("s2", title="shared", date="260101_000000"),
        _sdd("s1", title="shared", date="260101_000000"),
        _local("ph_b", title="shared", date="260101_000000"),
        _local("ph_a", title="shared", date="260101_000000"),
    ]
    first = _ids(search_prompts("shared", hits))
    second = _ids(search_prompts("shared", list(reversed(hits))))
    assert first == second == ["s1", "s2", "ph_a", "ph_b"]
