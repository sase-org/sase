"""Tests for saved common-placeholder ranking."""

from __future__ import annotations

from pathlib import Path

import pytest

import sase.history.prompt_placeholders as store
from sase.history.prompt_placeholders import (
    CommonPlaceholderIndex,
    _PlaceholderEntry,
    load_common_placeholder_index,
    load_common_placeholders,
    record_prompt_placeholders,
)
from sase.history.prompt_placeholder_ranking import (
    FREQUENCY_WEIGHT,
    RECENCY_WEIGHT,
    RELATION_MIN_PROMPTS,
    RELATION_WEIGHT,
    RankedPlaceholder,
    build_placeholder_ranking_context,
    rank_common_placeholders,
    rank_recent_common_placeholders,
)
from sase.history.prompt_word_index import _parse_sase_timestamp_epoch
from tests.conftest import redirect_sase_home


def _epoch(timestamp: str) -> float:
    return _parse_sase_timestamp_epoch(timestamp)


def _entry(
    text: str,
    *,
    count: int,
    last_used: str,
    context: dict[str, int] | None = None,
    context_uses: int | None = None,
) -> _PlaceholderEntry:
    bag = {} if context is None else dict(context)
    return _PlaceholderEntry(
        text=text,
        count=count,
        last_used=last_used,
        context_uses=count if context_uses is None else context_uses,
        context=bag,
    )


def _index(
    *entries: _PlaceholderEntry,
    prompt_count: int,
    context_frequency: dict[str, int] | None = None,
) -> CommonPlaceholderIndex:
    return CommonPlaceholderIndex(
        entries=entries,
        prompt_count=prompt_count,
        context_frequency={} if context_frequency is None else dict(context_frequency),
        max_count=max((entry.count for entry in entries), default=0),
    )


def _rank(
    index: CommonPlaceholderIndex,
    text: str,
    *,
    now: float,
) -> list[RankedPlaceholder]:
    context = build_placeholder_ranking_context(index, text, now=now)
    return rank_common_placeholders(index, context, now=now)


def _by_text(ranked: list[RankedPlaceholder]) -> dict[str, RankedPlaceholder]:
    return {item.text: item for item in ranked}


def _freeze_timestamps(monkeypatch: pytest.MonkeyPatch, timestamps: list[str]) -> None:
    pending = list(timestamps)

    def _next() -> str:
        return pending.pop(0) if len(pending) > 1 else pending[0]

    monkeypatch.setattr(store, "generate_timestamp", _next)


@pytest.fixture
def sase_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setattr(
        store,
        "load_merged_config",
        lambda: {"ace": {"prompt_completion": {"common_placeholder_count": 100}}},
    )
    return home


def test_related_tag_outranks_more_recent_frequent_unrelated_and_flips_without_context() -> (
    None
):
    now = _epoch("260815_000000")
    index = _index(
        _entry(
            "phase title",
            count=2,
            last_used="260813_000000",
            context={
                "monitor": 2,
                "bravo": 2,
                "charlie": 2,
                "delta": 2,
            },
        ),
        _entry(
            "worker",
            count=4,
            last_used="260815_000000",
            context={"filler": 4},
        ),
        prompt_count=16,
        context_frequency={
            "monitor": 2,
            "bravo": 2,
            "charlie": 2,
            "delta": 2,
            "filler": 4,
        },
    )

    with_context = _rank(index, "please monitor bravo charlie delta", now=now)
    without_context = _rank(index, "please write something", now=now)

    assert [item.text for item in with_context] == ["phase title", "worker"]
    related = _by_text(with_context)["phase title"]
    assert related.reason == "relation"
    assert related.related_to == "bravo"
    assert [item.text for item in without_context] == ["worker", "phase title"]


def test_cooccurring_placeholder_lifts_with_bracketed_related_to() -> None:
    now = _epoch("260815_000000")
    index = _index(
        _entry(
            "phase title",
            count=2,
            last_used="260701_000000",
            context={"<epic name>": 2},
        ),
        _entry(
            "worker",
            count=3,
            last_used="260701_000000",
            context={"filler": 3},
        ),
        prompt_count=16,
        context_frequency={"<epic name>": 2, "filler": 3},
    )

    ranked = _rank(index, "ship the <epic name> today", now=now)
    related = _by_text(ranked)["phase title"]

    assert related.reason == "relation"
    assert related.related_to == "<epic name>"
    assert ranked[0].text == "phase title"


def test_globally_common_tag_gets_no_relation_lift() -> None:
    now = _epoch("260815_000000")
    index = _index(
        _entry(
            "ubiquitous",
            count=14,
            last_used="260815_000000",
            context={"signal": 14},
        ),
        _entry(
            "correlate",
            count=2,
            last_used="260815_000000",
            context={
                "signal": 2,
                "uniquea": 2,
                "uniqueb": 2,
                "uniquec": 2,
            },
        ),
        prompt_count=16,
        context_frequency={
            "signal": 16,
            "uniquea": 2,
            "uniqueb": 2,
            "uniquec": 2,
        },
    )

    ranked = _rank(index, "signal uniquea uniqueb uniquec", now=now)
    by_text = _by_text(ranked)

    assert by_text["ubiquitous"].relation == 0.0
    assert by_text["correlate"].relation > 0.0
    assert [item.text for item in ranked] == ["correlate", "ubiquitous"]


def test_relation_shrinkage_rewards_repeated_related_hits() -> None:
    now = _epoch("260815_000000")
    index = _index(
        _entry("single", count=3, last_used="260815_000000", context={"anchor": 3}),
        _entry(
            "multi",
            count=3,
            last_used="260815_000000",
            context={
                "anchor": 3,
                "bravo": 3,
                "charlie": 3,
                "delta": 3,
            },
        ),
        prompt_count=24,
        context_frequency={
            "anchor": 3,
            "bravo": 3,
            "charlie": 3,
            "delta": 3,
        },
    )

    ranked = _rank(index, "anchor bravo charlie delta", now=now)
    by_text = _by_text(ranked)

    assert by_text["single"].relation > 0.0
    assert by_text["multi"].relation > by_text["single"].relation


def test_recency_halves_at_half_life_clamps_future_and_ranks_unparsable_last() -> None:
    now = _epoch("260815_000000")
    index = _index(
        _entry("agefuture", count=1, last_used="260816_000000"),
        _entry("agehalf", count=1, last_used="260801_000000"),
        _entry("agebad", count=1, last_used="not-a-timestamp"),
        prompt_count=8,
    )

    ranked = _rank(index, "", now=now)
    by_text = _by_text(ranked)

    assert by_text["agefuture"].recency == pytest.approx(RECENCY_WEIGHT)
    assert by_text["agehalf"].recency == pytest.approx(RECENCY_WEIGHT * 0.5)
    assert [item.text for item in ranked] == ["agefuture", "agehalf", "agebad"]


def test_frequency_saturates_and_cannot_outrank_relation_plus_recency() -> None:
    now = _epoch("260815_000000")
    index = _index(
        _entry("common", count=8, last_used="260801_000000"),
        _entry(
            "rare",
            count=1,
            last_used="260815_000000",
            context={
                "monitor": 1,
                "bravo": 1,
                "charlie": 1,
                "delta": 1,
            },
        ),
        prompt_count=16,
        context_frequency={
            "monitor": 1,
            "bravo": 1,
            "charlie": 1,
            "delta": 1,
        },
    )

    ranked = _rank(index, "please monitor bravo charlie delta", now=now)
    by_text = _by_text(ranked)

    assert by_text["common"].frequency == pytest.approx(FREQUENCY_WEIGHT)
    assert 0.0 < by_text["rare"].frequency < by_text["common"].frequency
    assert (
        by_text["common"].frequency < by_text["rare"].relation + by_text["rare"].recency
    )
    assert [item.text for item in ranked] == ["rare", "common"]


def test_small_corpus_empty_vocabulary_and_empty_context_zero_relation() -> None:
    now = _epoch("260815_000000")
    related = {
        "monitor": 2,
        "bravo": 2,
    }
    small = _index(
        _entry("phase title", count=2, last_used="260815_000000", context=related),
        prompt_count=RELATION_MIN_PROMPTS - 1,
        context_frequency=related,
    )
    empty_vocab = _index(
        _entry("phase title", count=2, last_used="260815_000000", context=related),
        prompt_count=16,
        context_frequency={},
    )
    no_context = _index(
        _entry("phase title", count=2, last_used="260815_000000", context=related),
        prompt_count=16,
        context_frequency=related,
    )

    assert all(item.relation == 0.0 for item in _rank(small, "monitor bravo", now=now))
    assert all(
        item.relation == 0.0 for item in _rank(empty_vocab, "monitor bravo", now=now)
    )
    assert all(item.relation == 0.0 for item in _rank(no_context, "", now=now))


def test_evicted_context_token_contributes_nothing() -> None:
    now = _epoch("260815_000000")
    index = _index(
        _entry(
            "alpha",
            count=2,
            last_used="260815_000000",
            context={"missingtok": 2},
        ),
        prompt_count=16,
        context_frequency={"monitor": 2},
    )

    ranked = _rank(index, "please monitor missingtok", now=now)

    assert ranked[0].relation == 0.0
    assert ranked[0].related_to == ""


def test_equal_scores_sort_by_folded_text_then_text_deterministically() -> None:
    now = _epoch("260815_000000")
    index = _index(
        _entry("Beta", count=1, last_used="260815_000000"),
        _entry("alpha", count=1, last_used="260815_000000"),
        _entry("Alpha", count=1, last_used="260815_000000"),
        prompt_count=8,
    )

    first = _rank(index, "", now=now)
    second = _rank(index, "", now=now)

    assert [item.text for item in first] == ["Alpha", "alpha", "Beta"]
    assert [item.text for item in second] == [item.text for item in first]


def test_ranking_context_memo_reuses_same_tokens_and_recomputes_different_tokens() -> (
    None
):
    now = _epoch("260815_000000")
    index = _index(
        _entry("phase title", count=2, last_used="260815_000000"),
        prompt_count=16,
        context_frequency={"monitor": 2, "worker": 2},
    )

    first = build_placeholder_ranking_context(index, "monitor the plan", now=now)
    second = build_placeholder_ranking_context(
        index,
        "monitor the plan",
        now=now + 60.0,
    )
    third = build_placeholder_ranking_context(index, "worker the plan", now=now)

    assert second is first
    assert third is not first
    assert first.tokens != third.tokens


def test_recent_mode_preserves_store_order_and_attaches_no_evidence(
    sase_home_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<beta> <gamma> <delta>")
    _freeze_timestamps(monkeypatch, ["260702_000000"])
    record_prompt_placeholders("<gamma>")
    _freeze_timestamps(monkeypatch, ["260703_000000"])
    record_prompt_placeholders("<delta>")
    _freeze_timestamps(monkeypatch, ["260701_000000"])
    record_prompt_placeholders("<epsilon>")

    now = _epoch("260815_000000")
    stored = load_common_placeholders(10)
    index = load_common_placeholder_index()
    ranked = rank_recent_common_placeholders(index, now=now)

    assert stored == ["delta", "gamma", "beta", "epsilon"]
    assert [item.text for item in ranked] == stored
    assert all(
        (item.score, item.relation, item.recency, item.frequency, item.related_to)
        == (0.0, 0.0, 0.0, 0.0, "")
        for item in ranked
    )
