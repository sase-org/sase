"""Recent word derivation from the sharded prompt-history store."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sase.ace.tui.widgets.prompt_word_completion import (
    is_word_character,
    is_prompt_word_candidate,
    word_ranges,
)
from sase.history.prompt_store import iter_shard_paths_newest_first, load_shard
from sase.history.prompt_word_deletions import (
    PromptWordDeletionsSourceToken,
    load_deleted_prompt_words,
    prompt_word_deletions_source_token,
)

HistoryWordsSourceToken = tuple[
    int,
    int,
    tuple[tuple[str, int, int], ...],
    PromptWordDeletionsSourceToken,
]


def _extract_prompt_words(text: str, *, min_length: int) -> Iterator[str]:
    """Yield useful identifier-like prompt words in source order."""
    minimum = max(1, min_length)
    for start, end in word_ranges(text):
        word = text[start:end]
        if (
            len(word) >= minimum
            and is_prompt_word_candidate(word)
            and _has_useful_history_content(word)
        ):
            yield word


def _has_useful_history_content(word: str) -> bool:
    """Return whether *word* has content beyond digits and ASCII hyphens."""
    return any(
        is_word_character(character) and not character.isdigit() and character != "-"
        for character in word
    )


def collect_recent_prompt_words(*, max_words: int, min_length: int) -> list[str]:
    """Return exact-spelling prompt words in most-recently-used order."""
    if max_words <= 0:
        return []

    deleted = load_deleted_prompt_words()
    words: list[str] = []
    seen: set[str] = set()
    for path in iter_shard_paths_newest_first():
        entries = load_shard(path)
        entries.sort(key=lambda entry: entry.last_used, reverse=True)
        for entry in entries:
            for word in _extract_prompt_words(entry.text, min_length=min_length):
                if word in deleted or word in seen:
                    continue
                seen.add(word)
                words.append(word)
                if len(words) >= max_words:
                    return words
    return words


def history_words_source_token(
    *,
    max_words: int,
    min_length: int,
) -> HistoryWordsSourceToken:
    """Return a cheap token for the history shards and derivation settings."""
    shards: list[tuple[str, int, int]] = []
    for path in iter_shard_paths_newest_first():
        shards.append(_shard_token(path))
    return (
        max_words,
        min_length,
        tuple(shards),
        prompt_word_deletions_source_token(),
    )


def _shard_token(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), stat.st_mtime_ns, stat.st_size)
