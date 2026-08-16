"""Recent word derivation from the sharded prompt-history store."""

from __future__ import annotations

from sase.history.prompt_store import iter_shard_paths_newest_first, load_shard
from sase.history.prompt_word_deletions import (
    PromptWordDeletionsSourceToken,
    load_deleted_prompt_words,
    prompt_word_deletions_source_token,
)
from sase.history.prompt_word_index import (
    PromptWordIndex,
    build_prompt_word_index,
    prompt_word_index_source_token,
)

HistoryWordsSourceToken = tuple[
    int,
    int,
    tuple[tuple[str, int, int], ...],
    PromptWordDeletionsSourceToken,
]


def collect_recent_prompt_words(*, max_words: int, min_length: int) -> list[str]:
    """Return exact-spelling prompt words in most-recently-used order."""
    if max_words <= 0:
        return []

    deleted = load_deleted_prompt_words()
    index = build_prompt_word_index(
        min_length=min_length,
        shard_limit=None,
        prompt_limit=None,
        shard_paths=iter_shard_paths_newest_first(),
        load_shard_func=load_shard,
        stop_after_mru_words=max_words,
        deleted_words=deleted,
    )
    return _collect_recent_words_from_index(
        index,
        max_words=max_words,
        deleted_words=deleted,
    )


def _collect_recent_words_from_index(
    index: PromptWordIndex,
    *,
    max_words: int,
    deleted_words: set[str] | frozenset[str],
) -> list[str]:
    words: list[str] = []
    for word_id in index.mru:
        word = index.spelling(word_id)
        if word in deleted_words:
            continue
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
    index_token = prompt_word_index_source_token(
        min_length=min_length,
        shard_limit=None,
        shard_paths=iter_shard_paths_newest_first(),
    )
    return (
        max_words,
        min_length,
        index_token[2],
        prompt_word_deletions_source_token(),
    )
