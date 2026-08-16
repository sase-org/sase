"""Prompt-history word completion for the manual prompt completion menu."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_word_completion import (
    WordCompletionResult,
    shared_word_extension,
    word_range_at_cursor,
)
from sase.history.prompt_word_index import PromptWordIndex
from sase.history.prompt_word_ranking import (
    RankedWord,
    build_word_ranking_context,
    rank_history_words,
    rank_recent_history_words,
)

HISTORY_WORD_COMPLETION_KIND = "history_word"


@dataclass(frozen=True, slots=True)
class HistoryWordCompletionPlaceholder:
    """Non-selectable placeholder while prompt-history words are loading."""

    message: str


@dataclass(frozen=True, slots=True)
class HistoryWordCompletionMetadata:
    """Ranking evidence carried by one smart-ranked history-word candidate."""

    reason: str
    related_to: str
    use_count: int
    age_seconds: float
    score: float
    relation: float
    recency: float
    frequency: float


def build_history_word_completion_result(
    text: str,
    cursor_offset: int,
    words: list[str],
) -> WordCompletionResult | None:
    """Return MRU history-word matches for the prefix left of the cursor.

    Only the left-side prefix filters the warm MRU word list; any right-hand
    suffix under the cursor is neither used to include nor exclude candidates,
    and the replacement range covers just the typed prefix so that suffix is
    preserved on acceptance. An MRU word that exactly matches the typed prefix
    is only offered when the cursor also has a right-hand suffix to separate,
    since otherwise accepting it would have no effect.
    """
    word_range = word_range_at_cursor(text, cursor_offset)
    if word_range is None:
        return None
    word_start, word_end = word_range
    prefix = text[word_start:cursor_offset]
    has_word_suffix = word_end > cursor_offset
    prefix_folded = prefix.casefold()

    ordered: list[str] = []
    seen: set[str] = set()
    for word in words:
        if word in seen:
            continue
        seen.add(word)
        if not word.casefold().startswith(prefix_folded):
            continue
        if word == prefix and not has_word_suffix:
            continue
        ordered.append(word)

    if not ordered:
        return None

    candidates = [
        CompletionCandidate(
            display=word,
            insertion=word,
            is_dir=False,
            name=word,
        )
        for word in ordered
    ]
    return WordCompletionResult(
        prefix=prefix,
        replacement_start=word_start,
        replacement_end=cursor_offset,
        candidates=candidates,
        shared_extension=shared_word_extension(ordered, prefix),
        has_word_suffix=has_word_suffix,
    )


def build_indexed_history_word_completion_result(
    text: str,
    cursor_offset: int,
    index: PromptWordIndex,
    *,
    deleted: set[str] | frozenset[str],
    now: float,
    smart: bool,
) -> WordCompletionResult | None:
    """Return index-backed history-word matches for the prefix left of the cursor.

    Mirrors :func:`build_history_word_completion_result`'s prefix, replacement
    range, and exact-spelling-suppression rules. When *smart* is set,
    candidates are ordered by the relation/recency/frequency composite score
    and carry :class:`HistoryWordCompletionMetadata` evidence; otherwise they
    reproduce plain MRU order (``word_ranking: recent``) with no metadata, so
    every row downstream is the same :class:`RankedWord`-derived shape either
    way.
    """
    word_range = word_range_at_cursor(text, cursor_offset)
    if word_range is None:
        return None
    word_start, word_end = word_range
    prefix = text[word_start:cursor_offset]
    has_word_suffix = word_end > cursor_offset
    exclude_exact = None if has_word_suffix else prefix

    if smart:
        context = build_word_ranking_context(
            index,
            text,
            exclude_range=word_range,
            now=now,
        )
        ranked, extension_source = rank_history_words(
            index,
            context,
            prefix=prefix,
            deleted=deleted,
            exclude_exact=exclude_exact,
            now=now,
        )
    else:
        ranked, extension_source = rank_recent_history_words(
            index,
            prefix=prefix,
            deleted=deleted,
            exclude_exact=exclude_exact,
            now=now,
        )
    if not ranked:
        return None

    candidates = [_indexed_history_word_candidate(item, smart=smart) for item in ranked]
    return WordCompletionResult(
        prefix=prefix,
        replacement_start=word_start,
        replacement_end=cursor_offset,
        candidates=candidates,
        shared_extension=shared_word_extension(extension_source, prefix),
        has_word_suffix=has_word_suffix,
    )


def _indexed_history_word_candidate(
    item: RankedWord,
    *,
    smart: bool,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=item.word,
        insertion=item.word,
        is_dir=False,
        name=item.word,
        metadata=(
            HistoryWordCompletionMetadata(
                reason=item.reason,
                related_to=item.related_to,
                use_count=item.use_count,
                age_seconds=item.age_seconds,
                score=item.score,
                relation=item.relation,
                recency=item.recency,
                frequency=item.frequency,
            )
            if smart
            else None
        ),
    )


def build_loading_history_words_placeholder() -> CompletionCandidate:
    """Return the non-selectable row shown while history words load."""
    message = "loading history words…"
    return CompletionCandidate(
        display=message,
        insertion="",
        is_dir=False,
        name="",
        metadata=HistoryWordCompletionPlaceholder(message=message),
    )
