"""Tests for prompt-history word ranking."""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from sase.history.prompt_store import PromptEntry
from sase.history.prompt_word_index import (
    _parse_sase_timestamp_epoch,
    build_prompt_word_index,
)
from sase.history.prompt_word_ranking import (
    FREQUENCY_WEIGHT,
    RECENCY_WEIGHT,
    RELATION_WEIGHT,
    RankedWord,
    build_word_ranking_context,
    rank_history_words,
    rank_recent_history_words,
)


def _entry(text: str, last_used: str) -> PromptEntry:
    return PromptEntry(text=text, timestamp=last_used, last_used=last_used)


def _index(entries: list[PromptEntry]):
    return build_prompt_word_index(
        min_length=1,
        shard_limit=None,
        prompt_limit=None,
        shard_paths=[Path("ranking-test.json")],
        load_shard_func=lambda _path: list(entries),
    )


def _epoch(timestamp: str) -> float:
    return _parse_sase_timestamp_epoch(timestamp)


def _exclude(text: str, word: str) -> tuple[int, int]:
    start = text.index(word)
    return (start, start + len(word))


def _ranked_by_word(ranked: list[RankedWord]) -> dict[str, RankedWord]:
    return {word.word: word for word in ranked}


def _rank(
    index,
    text: str,
    *,
    active_word: str,
    prefix: str,
    now: float,
    limit: int = 200,
) -> tuple[list[RankedWord], list[str]]:
    context = build_word_ranking_context(
        index,
        text,
        exclude_range=_exclude(text, active_word),
        now=now,
    )
    return rank_history_words(
        index,
        context,
        prefix=prefix,
        deleted=frozenset(),
        exclude_exact=active_word,
        now=now,
        limit=limit,
    )


def test_related_word_outranks_more_recent_unrelated_word_and_flips_without_context() -> (
    None
):
    now = _epoch("260801_000000")
    entries = [
        _entry("render fresh0", "260730_000000"),
        _entry("monitor reconcile related0", "260701_000000"),
        _entry("monitor reconcile related1", "260630_000000"),
        *[
            _entry(f"background{i} filler{i}", f"2606{20 - i:02d}_000000")
            for i in range(9)
        ],
    ]
    index = _index(entries)

    with_context, _ = _rank(
        index,
        "please monitor re",
        active_word="re",
        prefix="re",
        now=now,
    )
    without_context, _ = _rank(
        index,
        "please re",
        active_word="re",
        prefix="re",
        now=now,
    )

    assert [word.word for word in with_context[:2]] == ["reconcile", "render"]
    assert _ranked_by_word(with_context)["reconcile"].reason == "relation"
    assert _ranked_by_word(with_context)["reconcile"].related_to == "monitor"
    assert [word.word for word in without_context[:2]] == ["render", "reconcile"]


def test_globally_common_word_gets_no_relation_lift() -> None:
    now = _epoch("260802_000000")
    entries = [
        _entry("signal correlate commonword", "260801_000000"),
        _entry("signal correlate commonword", "260731_000000"),
        *[
            _entry(f"commonword filler{i}", f"2607{20 - i:02d}_000000")
            for i in range(8)
        ],
    ]
    index = _index(entries)

    context = build_word_ranking_context(
        index,
        "signal co",
        exclude_range=_exclude("signal co", "co"),
        now=now,
    )
    ranked, _ = rank_history_words(
        index,
        context,
        prefix="co",
        deleted=frozenset(),
        exclude_exact="co",
        now=now,
    )

    common_id = index.words.index("commonword")
    assert context.relation_by_word_id.get(common_id, 0.0) == 0.0
    assert [word.word for word in ranked[:2]] == ["correlate", "commonword"]


def test_relation_shrinkage_rewards_repeated_related_hits() -> None:
    now = _epoch("260802_000000")
    related = [
        _entry(
            f"anchor multi {'single' if index == 0 else f'related{index}'}",
            f"2607{31 - index:02d}_000000",
        )
        for index in range(4)
    ]
    entries = [
        *related,
        *[
            _entry(f"background{i} filler{i}", f"2606{20 - i:02d}_000000")
            for i in range(20)
        ],
    ]
    index = _index(entries)

    context = build_word_ranking_context(
        index,
        "anchor m",
        exclude_range=_exclude("anchor m", "m"),
        now=now,
    )

    single_id = index.words.index("single")
    multi_id = index.words.index("multi")
    assert context.relation_by_word_id[single_id] > 0.0
    assert (
        context.relation_by_word_id[multi_id] > context.relation_by_word_id[single_id]
    )


def test_recency_decay_future_clamp_and_unparsable_timestamp_ordering() -> None:
    now = _epoch("260801_000000")
    index = _index(
        [
            _entry("agefuture", "260802_000000"),
            _entry("agehalf", "260725_000000"),
            _entry("agebad", "not-a-timestamp"),
        ]
    )
    context = build_word_ranking_context(index, "", exclude_range=None, now=now)

    ranked, _ = rank_history_words(
        index,
        context,
        prefix="age",
        deleted=frozenset(),
        exclude_exact=None,
        now=now,
    )
    by_word = _ranked_by_word(ranked)

    assert by_word["agefuture"].recency == pytest.approx(RECENCY_WEIGHT)
    assert by_word["agehalf"].recency == pytest.approx(RECENCY_WEIGHT * 0.5)
    assert [word.word for word in ranked] == ["agefuture", "agehalf", "agebad"]


def test_frequency_saturates_without_exceeding_the_other_signal_pair() -> None:
    now = _epoch("260801_000000")
    index = _index(
        [
            _entry("common rare", "260801_000000"),
            *[
                _entry(f"common filler{i}", f"2607{31 - i:02d}_000000")
                for i in range(4)
            ],
        ]
    )
    context = build_word_ranking_context(index, "", exclude_range=None, now=now)

    ranked, _ = rank_history_words(
        index,
        context,
        prefix="",
        deleted=frozenset(),
        exclude_exact=None,
        now=now,
    )
    by_word = _ranked_by_word(ranked)

    assert by_word["common"].frequency == pytest.approx(FREQUENCY_WEIGHT)
    assert 0.0 < by_word["rare"].frequency < by_word["common"].frequency
    assert by_word["common"].frequency < RELATION_WEIGHT + RECENCY_WEIGHT


def test_small_corpus_disables_relation_scores() -> None:
    now = _epoch("260801_000000")
    index = _index(
        [
            _entry("anchor associated", "260801_000000"),
            *[
                _entry(f"background{i} filler{i}", f"2607{31 - i:02d}_000000")
                for i in range(6)
            ],
        ]
    )

    ranked, _ = _rank(
        index,
        "anchor as",
        active_word="as",
        prefix="as",
        now=now,
    )

    assert all(word.relation == 0.0 for word in ranked)


def test_context_extraction_skips_cursor_word_includes_later_words_and_drops_stopwords() -> (
    None
):
    now = _epoch("260801_000000")
    index = _index(
        [
            _entry("active one", "260801_000000"),
            _entry("later two", "260731_000000"),
            _entry("common three", "260730_000000"),
            _entry("common four", "260729_000000"),
            _entry("common five", "260728_000000"),
            *[
                _entry(f"background{i} filler{i}", f"2607{20 - i:02d}_000000")
                for i in range(5)
            ],
        ]
    )

    context = build_word_ranking_context(
        index,
        "active later common",
        exclude_range=_exclude("active later common", "active"),
        now=now,
    )

    assert index.words.index("later") in context.context_key
    assert index.words.index("active") not in context.context_key
    assert index.words.index("common") not in context.context_key


def test_equal_scores_sort_by_folded_spelling_then_spelling_deterministically() -> None:
    now = _epoch("260801_000000")
    index = _index([_entry("Beta alpha Alpha", "260801_000000")])
    context = build_word_ranking_context(index, "", exclude_range=None, now=now)

    first, _ = rank_history_words(
        index,
        context,
        prefix="",
        deleted=frozenset(),
        exclude_exact=None,
        now=now,
    )
    second, _ = rank_history_words(
        index,
        context,
        prefix="",
        deleted=frozenset(),
        exclude_exact=None,
        now=now,
    )

    assert [word.word for word in first] == ["Alpha", "alpha", "Beta"]
    assert [word.word for word in second] == [word.word for word in first]


def test_ranking_context_memo_reuses_same_context_key_and_recomputes_different_key() -> (
    None
):
    now = _epoch("260801_000000")
    index = _index(
        [
            _entry("anchor one", "260801_000000"),
            _entry("extra two", "260731_000000"),
            *[
                _entry(f"background{i} filler{i}", f"2607{20 - i:02d}_000000")
                for i in range(8)
            ],
        ]
    )

    first = build_word_ranking_context(
        index,
        "anchor wor",
        exclude_range=_exclude("anchor wor", "wor"),
        now=now,
    )
    second = build_word_ranking_context(
        index,
        "anchor word",
        exclude_range=_exclude("anchor word", "word"),
        now=now + 60.0,
    )
    third = build_word_ranking_context(
        index,
        "extra word",
        exclude_range=_exclude("extra word", "word"),
        now=now,
    )

    assert second is first
    assert third is not first


def test_shared_extension_source_includes_matches_beyond_limit() -> None:
    now = _epoch("260801_000000")
    index = _index([_entry("foobaz foobar foodle", "260801_000000")])
    context = build_word_ranking_context(index, "", exclude_range=None, now=now)

    ranked, source = rank_history_words(
        index,
        context,
        prefix="foo",
        deleted=frozenset(),
        exclude_exact=None,
        now=now,
        limit=1,
    )

    assert len(ranked) == 1
    assert source == ["foobar", "foobaz", "foodle"]


def test_recent_ranking_preserves_mru_filter_with_zero_contributions() -> None:
    now = _epoch("260801_000000")
    index = _index(
        [
            _entry("review remove", "260801_000000"),
            _entry("revise review", "260731_000000"),
            _entry("reply", "260730_000000"),
        ]
    )

    ranked, source = rank_recent_history_words(
        index,
        prefix="re",
        deleted={"remove"},
        exclude_exact=None,
        now=now,
        limit=2,
    )

    assert [word.word for word in ranked] == ["review", "revise"]
    assert source == ["review", "revise", "reply"]
    assert all(
        (word.score, word.relation, word.recency, word.frequency)
        == (0.0, 0.0, 0.0, 0.0)
        for word in ranked
    )


@pytest.mark.slow
def test_ranking_large_synthetic_corpus_stays_fast() -> None:
    now = _epoch("260801_000000")
    entries = [
        _entry(
            f"{'anchor ' if index % 100 == 0 else ''}target{index % 500} filler{index}",
            f"2607{(index % 28) + 1:02d}_000000",
        )
        for index in range(5000)
    ]
    index = _index(entries)

    started = time.perf_counter()
    ranked, source = _rank(
        index,
        "anchor tar",
        active_word="tar",
        prefix="target",
        now=now,
    )
    elapsed = time.perf_counter() - started

    assert ranked
    assert source
    assert elapsed < 1.0
