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
    suffix of the current word) are never candidates. Case variants of the
    same word collapse into one row. A candidate whose computed insertion
    exactly matches the typed prefix is only offered when the cursor also has
    a right-hand suffix to separate, since otherwise accepting it would have
    no effect. The minimum applies to complete candidates, not to the typed
    prefix. Candidates are ordered nearest-first: by the latest offset each
    distinct folded spelling starts at before the active word, since the word
    you just wrote is the one you are most likely repeating.
    """
    word_range = word_range_at_cursor(text, cursor_offset)
    if word_range is None:
        return None
    word_start, word_end = word_range
    prefix = text[word_start:cursor_offset]
    has_word_suffix = word_end > cursor_offset
    prefix_folded = prefix.casefold()

    minimum = max(1, min_length)
    latest_by_fold: dict[str, tuple[str, int]] = {}
    for start, end in _word_ranges(text):
        if start >= word_start:
            break
        word = text[start:end]
        if (
            len(word) < minimum
            or not is_prompt_word_candidate(word)
            or not word.casefold().startswith(prefix_folded)
        ):
            continue
        latest_by_fold[word.casefold()] = (word, start)

    if not latest_by_fold:
        return None

    ordered = [
        word
        for word, _start in sorted(
            latest_by_fold.values(),
            key=lambda item: -item[1],
        )
    ]
    candidates: list[CompletionCandidate] = []
    extension_source: list[str] = []
    for word in ordered:
        insertion = apply_word_case(word, prefix)
        if insertion == prefix and not has_word_suffix:
            continue
        extension_source.append(word)
        candidates.append(
            CompletionCandidate(
                display=insertion,
                insertion=insertion,
                is_dir=False,
                name=word,
            )
        )
    if not candidates:
        return None

    return WordCompletionResult(
        prefix=prefix,
        replacement_start=word_start,
        replacement_end=cursor_offset,
        candidates=candidates,
        shared_extension=shared_word_extension(extension_source, prefix),
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


def _word_ranges(text: str) -> Iterator[tuple[int, int]]:
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


def apply_word_case(canonical: str, prefix: str) -> str:
    """Return *canonical* re-cased to honor the casing typed in *prefix*.

    ``canonical`` is expected to casefold-start with ``prefix``. If the folded
    prefix does not align to a character boundary in ``canonical`` (for
    example ``stras`` against ``Straße``), the canonical spelling is returned
    unchanged except for an explicit shout prefix. A prefix shouts when it has
    at least two cased characters and all of them are uppercase; shouting
    uppercases the remainder too, so ``GITHU`` completes ``GitHub`` as
    ``GITHUB``. Otherwise, canonical spellings with intrinsic uppercase
    letters after their first cased character (``GitHub``, ``README``,
    ``iPhone``) stay intact; plain words keep the typed prefix and take the
    remainder from history.
    """
    split = _casefold_prefix_split(canonical, prefix)
    if _is_shout_prefix(prefix):
        if split is None:
            shouted = canonical.upper()
            return (
                shouted
                if shouted.casefold().startswith(prefix.casefold())
                else canonical
            )
        return f"{prefix}{canonical[split:].upper()}"

    if split is None:
        return canonical
    if _has_intrinsic_uppercase(canonical):
        return canonical
    return f"{prefix}{canonical[split:]}"


def shared_word_extension(insertions: list[str], prefix: str) -> str:
    """Return the re-cased case-insensitive common suffix beyond *prefix*."""
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

    split = _casefold_prefix_split(shared, prefix)
    if split is None or split >= len(shared):
        return ""
    recased = apply_word_case(shared, prefix)
    if not recased.casefold().startswith(prefix.casefold()):
        return ""
    return recased[len(prefix) :]


def _casefold_prefix_split(canonical: str, prefix: str) -> int | None:
    """Return the smallest character split matching the folded prefix."""
    folded = prefix.casefold()
    for split in range(len(canonical) + 1):
        if canonical[:split].casefold() == folded:
            return split
    return None


def _is_cased_character(character: str) -> bool:
    return character.lower() != character.upper()


def _is_shout_prefix(prefix: str) -> bool:
    cased = [character for character in prefix if _is_cased_character(character)]
    return len(cased) >= 2 and all(character.isupper() for character in cased)


def _has_intrinsic_uppercase(canonical: str) -> bool:
    seen_first_cased = False
    for character in canonical:
        if not _is_cased_character(character):
            continue
        if not seen_first_cased:
            seen_first_cased = True
            continue
        if character.isupper():
            return True
    return False
