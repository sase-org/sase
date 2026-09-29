"""Tests for n-gram context promotion of current-word menu candidates."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets._prompt_context_ranking import (
    CONTEXT_METER_WEIGHT,
    apply_context_promotion,
    _context_chip_text,
    _context_promotion_lookup,
    has_context_promotion,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_labels import (
    prompt_word_completion_subtitle,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_simple import (
    append_prompt_word_completion_row,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HistoryWordCompletionMetadata,
)
from sase.core.prompt_prediction_wire import (
    PromptPrefixRankMatch,
    PromptPrefixRankResult,
)


def _match(
    word: str, score: float, order: int = 2, support: int = 3
) -> PromptPrefixRankMatch:
    return PromptPrefixRankMatch(
        word=word, key=word.casefold(), score=score, order=order, support=support
    )


def _result(
    matches: list[PromptPrefixRankMatch],
    context_words: list[str] | None = None,
) -> PromptPrefixRankResult:
    return PromptPrefixRankResult(
        schema_version=1,
        context_words=list(
            context_words if context_words is not None else ["help", "me"]
        ),
        matches=list(matches),
    )


def _plain(word: str) -> CompletionCandidate:
    return CompletionCandidate(display=word, insertion=word, is_dir=False, name=word)


def _ranked(word: str, score: float = 0.4) -> CompletionCandidate:
    return CompletionCandidate(
        display=word,
        insertion=word,
        is_dir=False,
        name=word,
        metadata=HistoryWordCompletionMetadata(
            reason="recency",
            related_to="",
            use_count=1,
            age_seconds=60.0,
            score=score,
            relation=0.0,
            recency=0.3,
            frequency=0.1,
        ),
    )


def test_lookup_drops_deleted_and_empty_keys() -> None:
    lookup = _context_promotion_lookup(
        [_match("implement", 0.8), _match("", 0.9), _match("review", 0.2)],
        deleted={"review"},
    )

    assert set(lookup) == {"implement"}


def test_chip_text_names_last_three_evidence_words() -> None:
    assert _context_chip_text(["can", "you", "help", "me"]) == "you help me"
    assert _context_chip_text(["help", "me"]) == "help me"
    assert _context_chip_text([]) == ""


def test_none_result_returns_candidates_unchanged() -> None:
    candidates = [_plain("implement"), _plain("important")]

    assert apply_context_promotion(candidates, None) is candidates


def test_no_overlapping_match_returns_candidates_unchanged() -> None:
    candidates = [_plain("implement")]

    assert (
        apply_context_promotion(candidates, _result([_match("review", 0.8)]))
        is candidates
    )


def test_promoted_rows_sort_first_by_model_score() -> None:
    candidates = [_plain("zebra"), _plain("implement"), _plain("important")]

    ordered = apply_context_promotion(
        candidates,
        _result([_match("important", 0.4), _match("implement", 0.9)]),
    )

    assert [candidate.name for candidate in ordered] == [
        "implement",
        "important",
        "zebra",
    ]


def test_promoted_plain_row_carries_fresh_context_evidence() -> None:
    ordered = apply_context_promotion(
        [_plain("implement")],
        _result([_match("implement", 0.8, order=2, support=5)]),
    )

    metadata = ordered[0].metadata
    assert isinstance(metadata, HistoryWordCompletionMetadata)
    assert metadata.reason == "context"
    assert metadata.context == CONTEXT_METER_WEIGHT * 0.8
    assert metadata.score == CONTEXT_METER_WEIGHT * 0.8
    assert metadata.context_order == 2
    assert metadata.context_support == 5
    assert metadata.context_words == "help me"
    assert has_context_promotion(ordered) is True


def test_promoted_ranked_row_keeps_base_signals_with_boosted_score() -> None:
    ordered = apply_context_promotion(
        [_ranked("implement", score=0.4)],
        _result([_match("implement", 0.6)]),
    )

    metadata = ordered[0].metadata
    assert isinstance(metadata, HistoryWordCompletionMetadata)
    assert metadata.reason == "context"
    assert metadata.recency == 0.3
    assert metadata.frequency == 0.1
    assert metadata.context == CONTEXT_METER_WEIGHT * 0.6
    assert metadata.score == 0.4 + CONTEXT_METER_WEIGHT * 0.6
    assert metadata.context_words == "help me"


def test_boosted_score_caps_at_one() -> None:
    ordered = apply_context_promotion(
        [_ranked("implement", score=0.9)],
        _result([_match("implement", 1.0)]),
    )

    metadata = ordered[0].metadata
    assert isinstance(metadata, HistoryWordCompletionMetadata)
    assert metadata.score == 1.0


def test_deleted_words_are_never_promoted() -> None:
    candidates = [_plain("implement"), _plain("important")]

    ordered = apply_context_promotion(
        candidates,
        _result([_match("implement", 0.9)]),
        deleted={"implement"},
    )

    assert ordered is candidates
    assert has_context_promotion(candidates) is False


def test_unpromoted_rows_keep_metadata_and_order() -> None:
    candidates = [_ranked("zebra", score=0.5), _plain("apple")]

    ordered = apply_context_promotion(
        candidates,
        _result([_match("apple", 0.9)]),
    )

    assert [candidate.name for candidate in ordered] == ["apple", "zebra"]
    assert ordered[1].metadata is candidates[0].metadata


def _render_prompt_word_row(
    candidate: CompletionCandidate,
    *,
    inner_width: int | None = 40,
    signals_enabled: bool = True,
) -> Text:
    content = Text()
    append_prompt_word_completion_row(
        content,
        candidate,
        False,
        inner_width=inner_width,
        signals_enabled=signals_enabled,
    )
    return content


def test_prompt_word_row_appends_context_chip_when_promoted() -> None:
    ordered = apply_context_promotion(
        [_plain("implementation"), _plain("zebra")],
        _result([_match("implementation", 0.8)]),
    )

    assert _render_prompt_word_row(ordered[0]).plain == "implementation  ⇢ help me"
    assert _render_prompt_word_row(ordered[1]).plain == "zebra"


def test_prompt_word_row_drops_chip_on_narrow_panel() -> None:
    ordered = apply_context_promotion(
        [_plain("implementation")],
        _result([_match("implementation", 0.8)]),
    )

    assert _render_prompt_word_row(ordered[0], inner_width=10).plain == "implementation"


def test_prompt_word_row_hides_chip_when_signals_disabled() -> None:
    ordered = apply_context_promotion(
        [_plain("implementation")],
        _result([_match("implementation", 0.8)]),
    )

    rendered = _render_prompt_word_row(ordered[0], signals_enabled=False)

    assert rendered.plain == "implementation"


def test_prompt_word_subtitle_names_context_legend_entry_when_promoted() -> None:
    ordered = apply_context_promotion(
        [_plain("implementation")],
        _result([_match("implementation", 0.8)]),
    )

    subtitle = prompt_word_completion_subtitle(ordered, 200)

    assert isinstance(subtitle, Text)
    assert "⇢ context" in subtitle.plain
    assert subtitle.plain.endswith("[^T] accept")


def test_prompt_word_subtitle_keeps_plain_hint_without_promotion() -> None:
    assert prompt_word_completion_subtitle([_plain("zebra")], 200) == "[^T] accept"
