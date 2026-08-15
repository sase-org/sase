"""Prompt-local word completion for the manual prompt completion menu."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from sase.ace.tui.widgets.file_completion import CompletionCandidate

PROMPT_WORD_COMPLETION_KIND = "prompt_word"


@dataclass(frozen=True, slots=True)
class WordCompletionResult:
    """Word completion context at one absolute cursor offset."""

    prefix: str
    replacement_start: int
    replacement_end: int
    candidates: list[CompletionCandidate]
    shared_extension: str


def build_prompt_word_completion_result(
    text: str,
    cursor_offset: int,
    *,
    min_length: int = 5,
) -> WordCompletionResult | None:
    """Return prompt-local word matches for the prefix left of the cursor.

    Words use the prompt widget's identifier-like semantics: a maximal run of
    Unicode alphanumeric characters, underscores, or ASCII hyphens. The cursor
    must have a non-empty word prefix immediately to its left. The result
    replaces the complete word around that prefix, including any suffix right
    of the cursor. The minimum applies to complete candidates, not to the typed
    prefix.
    """
    word_range = word_range_at_cursor(text, cursor_offset)
    if word_range is None:
        return None
    replacement_start, replacement_end = word_range
    prefix = text[replacement_start:cursor_offset]
    current_word = text[replacement_start:replacement_end]
    prefix_folded = prefix.casefold()

    minimum = max(1, min_length)
    spellings: set[str] = set()
    for start, end in word_ranges(text):
        if start == replacement_start and end == replacement_end:
            continue
        word = text[start:end]
        if (
            len(word) < minimum
            or word == current_word
            or not is_prompt_word_candidate(word)
            or not word.casefold().startswith(prefix_folded)
        ):
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
        replacement_start=replacement_start,
        replacement_end=replacement_end,
        candidates=candidates,
        shared_extension=shared_word_extension(ordered, prefix),
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
