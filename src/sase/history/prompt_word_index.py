"""Immutable prompt-word corpus index for prompt-history completions."""

from __future__ import annotations

from array import array
from bisect import bisect_left, bisect_right
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
import calendar
import logging
from pathlib import Path
import re
import time

from sase.ace.tui.widgets.prompt_word_completion import (
    is_word_character,
    is_prompt_word_candidate,
)
from sase.history.prompt_store import (
    PromptEntry,
    iter_shard_paths_newest_first,
    load_shard,
)

log = logging.getLogger(__name__)

_PROMPT_WORD_RE = re.compile(r"[\w\-]+")
_SHARD_CACHE_LIMIT = 32
_SOURCE_TOKEN_SHARD_LIMIT_DEFAULT = 24
_SOURCE_TOKEN_PROMPT_LIMIT_DEFAULT = 20000

PromptWordIndexToken = tuple[int, int | None, tuple[tuple[str, int, int], ...]]
_ShardCacheKey = tuple[str, int, int, int]
_TokenizedPrompt = tuple[tuple[str, ...], float]
_ShardTokenCache = OrderedDict[_ShardCacheKey, tuple[_TokenizedPrompt, ...]]

_shard_token_cache: _ShardTokenCache = OrderedDict()


@dataclass(frozen=True, slots=True)
class _PromptWordPostings:
    """Compressed sparse row postings for prompt and word ids."""

    offsets: array
    values: array

    def row(self, row_id: int) -> array:
        """Return a copy of the postings for one row."""
        start = self.offsets[row_id]
        end = self.offsets[row_id + 1]
        return self.values[start:end]


@dataclass(frozen=True, slots=True)
class PromptWordIndex:
    """Prompt-history word corpus indexed for MRU and prefix lookup."""

    words: tuple[str, ...]
    folded_order: tuple[int, ...]
    folded_keys: tuple[str, ...]
    document_frequency: array
    last_used_epoch: array
    mru: tuple[int, ...]
    prompt_words: _PromptWordPostings
    word_prompts: _PromptWordPostings
    prompt_epoch: array
    prompt_count: int
    max_document_frequency: int
    source_token: PromptWordIndexToken
    _ranking_memo: object | None = None

    def word_ids_with_prefix(self, prefix: str) -> range:
        """Return the range of ``folded_order`` rows matching *prefix*."""
        folded = prefix.casefold()
        start = bisect_left(self.folded_keys, folded)
        end = bisect_right(self.folded_keys, folded + "\uffff")
        return range(start, end)

    def word_ids_for_spelling(self, spelling: str) -> tuple[int, ...]:
        """Return exact case-insensitive matches for *spelling*."""
        folded = spelling.casefold()
        rows = self.word_ids_with_prefix(spelling)
        return tuple(
            word_id
            for row in rows
            if self.folded_keys[row] == folded
            for word_id in (self.folded_order[row],)
        )

    def spelling(self, word_id: int) -> str:
        """Return the exact spelling for one word id."""
        return self.words[word_id]

    def prompt_word_ids(self, prompt_id: int) -> array:
        """Return a copy of the word ids present in one prompt."""
        return self.prompt_words.row(prompt_id)

    def word_prompt_ids(self, word_id: int) -> array:
        """Return a copy of prompt ids containing one word."""
        return self.word_prompts.row(word_id)


def build_prompt_word_index(
    *,
    min_length: int,
    shard_limit: int | None = _SOURCE_TOKEN_SHARD_LIMIT_DEFAULT,
    prompt_limit: int | None = _SOURCE_TOKEN_PROMPT_LIMIT_DEFAULT,
    shard_paths: Iterable[Path] | None = None,
    load_shard_func: Callable[[Path], list[PromptEntry]] = load_shard,
    stop_after_mru_words: int | None = None,
    deleted_words: set[str] | frozenset[str] = frozenset(),
) -> PromptWordIndex:
    """Build an immutable word index from the prompt-history shards."""
    return _build_prompt_word_index_from_paths(
        iter_shard_paths_newest_first() if shard_paths is None else shard_paths,
        min_length=min_length,
        shard_limit=shard_limit,
        prompt_limit=prompt_limit,
        load_shard_func=load_shard_func,
        stop_after_mru_words=stop_after_mru_words,
        deleted_words=deleted_words,
    )


def prompt_word_index_source_token(
    *,
    min_length: int,
    shard_limit: int | None = _SOURCE_TOKEN_SHARD_LIMIT_DEFAULT,
    shard_paths: Iterable[Path] | None = None,
) -> PromptWordIndexToken:
    """Return a cheap token for the indexed prompt-history shards."""
    return _prompt_word_index_source_token_from_paths(
        iter_shard_paths_newest_first() if shard_paths is None else shard_paths,
        min_length=min_length,
        shard_limit=shard_limit,
    )


def clear_prompt_word_index_cache() -> None:
    """Clear cached per-shard prompt word tokenization."""
    _shard_token_cache.clear()


def _build_prompt_word_index_from_paths(
    shard_paths: Iterable[Path],
    *,
    min_length: int,
    shard_limit: int | None,
    prompt_limit: int | None,
    load_shard_func: Callable[[Path], list[PromptEntry]],
    stop_after_mru_words: int | None = None,
    deleted_words: set[str] | frozenset[str] = frozenset(),
) -> PromptWordIndex:
    paths = tuple(shard_paths)
    source_token = _prompt_word_index_source_token_from_paths(
        paths,
        min_length=min_length,
        shard_limit=shard_limit,
    )
    word_ids: dict[str, int] = {}
    words: list[str] = []
    word_postings: list[list[int]] = []
    prompt_word_rows: list[list[int]] = []
    prompt_epochs = array("d")
    last_used_epochs = array("d")
    returned_word_count = 0
    reached_prompt_limit = False
    reached_shard_limit = False

    for shard_index, path in enumerate(paths):
        if shard_limit is not None and shard_index >= shard_limit:
            reached_shard_limit = True
            break
        if prompt_limit is not None and len(prompt_word_rows) >= prompt_limit:
            reached_prompt_limit = True
            break

        shard_prompts = _cached_tokenized_shard(
            path,
            min_length=min_length,
            load_shard_func=load_shard_func,
        )
        for prompt_words, prompt_epoch in shard_prompts:
            if prompt_limit is not None and len(prompt_word_rows) >= prompt_limit:
                reached_prompt_limit = True
                break

            prompt_id = len(prompt_word_rows)
            prompt_word_ids: list[int] = []
            seen_in_prompt: set[int] = set()
            stop_after_prompt = False
            for word in prompt_words:
                word_id = word_ids.get(word)
                if word_id is None:
                    word_id = len(words)
                    word_ids[word] = word_id
                    words.append(word)
                    word_postings.append([])
                    last_used_epochs.append(prompt_epoch)
                    if stop_after_mru_words is not None and word not in deleted_words:
                        returned_word_count += 1
                        if returned_word_count >= stop_after_mru_words:
                            stop_after_prompt = True

                if word_id in seen_in_prompt:
                    if stop_after_prompt:
                        break
                    continue
                seen_in_prompt.add(word_id)
                prompt_word_ids.append(word_id)
                word_postings[word_id].append(prompt_id)
                if stop_after_prompt:
                    break

            prompt_word_rows.append(prompt_word_ids)
            prompt_epochs.append(prompt_epoch)
            if stop_after_prompt:
                break
        if reached_prompt_limit or (
            stop_after_mru_words is not None
            and returned_word_count >= stop_after_mru_words
        ):
            break

    if reached_shard_limit:
        log.info("Prompt word index stopped after shard_limit=%s", shard_limit)
    if reached_prompt_limit:
        log.info("Prompt word index stopped after prompt_limit=%s", prompt_limit)

    prompt_postings = _build_postings(prompt_word_rows)
    word_prompt_postings = _build_postings(word_postings)
    document_frequency = array("i", (len(postings) for postings in word_postings))
    max_document_frequency = max(document_frequency, default=0)
    folded_pairs = sorted(
        ((word.casefold(), word, word_id) for word_id, word in enumerate(words)),
        key=lambda item: (item[0], item[1]),
    )
    folded_keys = tuple(pair[0] for pair in folded_pairs)
    folded_order = tuple(pair[2] for pair in folded_pairs)

    return PromptWordIndex(
        words=tuple(words),
        folded_order=folded_order,
        folded_keys=folded_keys,
        document_frequency=document_frequency,
        last_used_epoch=last_used_epochs,
        mru=tuple(range(len(words))),
        prompt_words=prompt_postings,
        word_prompts=word_prompt_postings,
        prompt_epoch=prompt_epochs,
        prompt_count=len(prompt_word_rows),
        max_document_frequency=max_document_frequency,
        source_token=source_token,
    )


def _prompt_word_index_source_token_from_paths(
    shard_paths: Iterable[Path],
    *,
    min_length: int,
    shard_limit: int | None,
) -> PromptWordIndexToken:
    shards: list[tuple[str, int, int]] = []
    for shard_index, path in enumerate(shard_paths):
        if shard_limit is not None and shard_index >= shard_limit:
            break
        shards.append(_shard_token(path))
    return (min_length, shard_limit, tuple(shards))


def _cached_tokenized_shard(
    path: Path,
    *,
    min_length: int,
    load_shard_func: Callable[[Path], list[PromptEntry]],
) -> tuple[_TokenizedPrompt, ...]:
    token = _shard_token(path)
    cache_key = (token[0], token[1], token[2], min_length)
    can_cache = token[1] >= 0 and token[2] >= 0
    if can_cache:
        cached = _shard_token_cache.get(cache_key)
        if cached is not None:
            return cached

    entries = load_shard_func(path)
    entries.sort(key=lambda entry: entry.last_used, reverse=True)
    tokenized = tuple(
        (tuple(_extract_prompt_words(entry.text, min_length=min_length)), prompt_epoch)
        for entry in entries
        for prompt_epoch in (_parse_sase_timestamp_epoch(entry.last_used),)
    )
    if can_cache:
        _shard_token_cache[cache_key] = tokenized
        while len(_shard_token_cache) > _SHARD_CACHE_LIMIT:
            _shard_token_cache.popitem(last=False)
    return tokenized


def _extract_prompt_words(text: str, *, min_length: int) -> Iterator[str]:
    """Yield useful identifier-like prompt words in source order."""
    minimum = max(1, min_length)
    for match in _PROMPT_WORD_RE.finditer(text):
        word = match.group(0)
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


def _parse_sase_timestamp_epoch(timestamp: str) -> float:
    raw = timestamp.strip()
    if len(raw) != 13 or raw[6] != "_":
        return 0.0
    try:
        year = _full_year(int(raw[0:2]))
        month = int(raw[2:4])
        day = int(raw[4:6])
        hour = int(raw[7:9])
        minute = int(raw[9:11])
        second = int(raw[11:13])
    except ValueError:
        return 0.0
    if (
        not 1 <= month <= 12
        or not 1 <= day <= calendar.monthrange(year, month)[1]
        or not 0 <= hour <= 23
        or not 0 <= minute <= 59
        or not 0 <= second <= 59
    ):
        return 0.0
    try:
        return time.mktime((year, month, day, hour, minute, second, -1, -1, -1))
    except (OverflowError, ValueError):
        return 0.0


def _full_year(two_digit_year: int) -> int:
    if two_digit_year <= 68:
        return 2000 + two_digit_year
    return 1900 + two_digit_year


def _shard_token(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _build_postings(rows: list[list[int]]) -> _PromptWordPostings:
    offsets = array("i", [0])
    values = array("i")
    for row in rows:
        values.extend(row)
        offsets.append(len(values))
    return _PromptWordPostings(offsets=offsets, values=values)
