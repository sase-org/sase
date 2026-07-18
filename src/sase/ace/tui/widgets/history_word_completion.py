"""Prompt-history word completion for the manual prompt completion menu."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_word_completion import (
    WordCompletionResult,
    shared_word_extension,
    word_range_at_cursor,
)

HISTORY_WORD_COMPLETION_KIND = "history_word"


@dataclass(frozen=True, slots=True)
class HistoryWordCompletionPlaceholder:
    """Non-selectable placeholder while prompt-history words are loading."""

    message: str


def build_history_word_completion_result(
    text: str,
    cursor_offset: int,
    words: list[str],
) -> WordCompletionResult | None:
    """Return MRU history-word matches for the prefix left of the cursor."""
    word_range = word_range_at_cursor(text, cursor_offset)
    if word_range is None:
        return None
    replacement_start, replacement_end = word_range
    prefix = text[replacement_start:cursor_offset]
    current_word = text[replacement_start:replacement_end]
    prefix_folded = prefix.casefold()

    ordered: list[str] = []
    seen: set[str] = set()
    for word in words:
        if word in seen:
            continue
        seen.add(word)
        if word == current_word or not word.casefold().startswith(prefix_folded):
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
        replacement_start=replacement_start,
        replacement_end=replacement_end,
        candidates=candidates,
        shared_extension=shared_word_extension(ordered, prefix),
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
