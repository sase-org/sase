"""Prompt-local word completion for the manual prompt completion menu."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from sase.ace.tui.widgets.file_completion import CompletionCandidate

PROMPT_WORD_COMPLETION_KIND = "prompt_word"


@dataclass(frozen=True, slots=True)
class WordCompletionResult:
    """Word completion context for the typed prefix left of one cursor offset.

    ``replacement_start``/``replacement_end`` bound only the typed prefix, so
    accepting a candidate never touches any identifier-like suffix already
    sitting to the right of the cursor. ``has_word_suffix`` reports whether
    such a suffix exists, so acceptance can insert a single separating space
    between the committed word and that preserved suffix.
    """

    prefix: str
    replacement_start: int
    replacement_end: int
    candidates: list[CompletionCandidate]
    shared_extension: str
    has_word_suffix: bool


def build_prompt_word_completion_result(
    text: str,
    cursor_offset: int,
    *,
    min_length: int = 5,
) -> WordCompletionResult | None:
    """Return prompt-local word matches for the prefix left of the cursor.

    Words use the prompt widget's identifier-like semantics: a maximal run of
    Unicode alphanumeric characters, underscores, or ASCII hyphens. The cursor
    must have a non-empty word prefix immediately to its left. Candidates are
    drawn only from complete words that appear earlier in the prompt, before
    the active prefix; words later in the prompt (including any right-hand
    suffix of the current word) are never candidates. An earlier word whose
    spelling exactly matches the typed prefix is only offered when the cursor
    also has a right-hand suffix to separate, since otherwise accepting it
    would have no effect. The minimum applies to complete candidates, not to
    the typed prefix.
    """
    word_range = word_range_at_cursor(text, cursor_offset)
    if word_range is None:
        return None
    word_start, word_end = word_range
    prefix = text[word_start:cursor_offset]
    has_word_suffix = word_end > cursor_offset
    prefix_folded = prefix.casefold()

    minimum = max(1, min_length)
    spellings: set[str] = set()
    for start, end in word_ranges(text):
        if start >= word_start:
            break
        word = text[start:end]
        if (
            len(word) < minimum
            or not is_prompt_word_candidate(word)
            or not word.casefold().startswith(prefix_folded)
        ):
            continue
        if word == prefix and not has_word_suffix:
            continue
        spellings.add(word)

    if not spellings:
        return None

    ordered = sorted(spellings, key=lambda word: (word.casefold(), word))
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


def word_range_at_cursor(text: str, cursor_offset: int) -> tuple[int, int] | None:
    """Return the complete identifier-like word containing the cursor prefix."""
    if cursor_offset <= 0 or cursor_offset > len(text):
        return None
    if not is_word_character(text[cursor_offset - 1]):
        return None

    start = cursor_offset - 1
    while start > 0 and is_word_character(text[start - 1]):
        start -= 1

    end = cursor_offset
    while end < len(text) and is_word_character(text[end]):
        end += 1
    return start, end


def word_ranges(text: str) -> Iterator[tuple[int, int]]:
    """Yield absolute ranges for all identifier-like prompt words in source order."""
    start = 0
    while start < len(text):
        if not is_word_character(text[start]):
            start += 1
            continue
        end = start + 1
        while end < len(text) and is_word_character(text[end]):
            end += 1
        yield start, end
        start = end


def is_word_character(character: str) -> bool:
    return character in {"-", "_"} or character.isalnum()


def is_prompt_word_candidate(word: str) -> bool:
    """Return whether an identifier-like word is useful as a completion row."""
    return any(character != "-" for character in word)


def shared_word_extension(insertions: list[str], prefix: str) -> str:
    """Return the case-insensitive common suffix beyond *prefix*."""
    if len(insertions) <= 1:
        return ""

    shared = insertions[0]
    for insertion in insertions[1:]:
        max_len = min(len(shared), len(insertion))
        index = 0
        while (
            index < max_len and shared[index].casefold() == insertion[index].casefold()
        ):
            index += 1
        shared = shared[:index]
        if not shared:
            return ""

    # Case-folding can change string length (for example, ``ß`` -> ``ss``).
    # Only extend when the character slice aligns with the typed prefix.
    if (
        len(shared) <= len(prefix)
        or shared[: len(prefix)].casefold() != prefix.casefold()
    ):
        return ""
    return shared[len(prefix) :]
