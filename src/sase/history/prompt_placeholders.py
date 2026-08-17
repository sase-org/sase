"""Durable store of common ``<placeholder>`` tags written in prompts.

Every placeholder the user writes is recorded here so the ``<`` completion
menu can offer tags from earlier prompts beneath the ones found in the prompt
being edited.  The store is deliberately authoritative rather than derived
from prompt history on every read: ranking needs a use count over *all*
history, and short prompts that never enter prompt history still contribute
their tags.  Prompt history is consulted as a best-effort seed
(:func:`seed_common_placeholders_from_history`) when the store file is absent
or still at format version 1.

Two orderings are in play and they are not the same:

- **Retention** is least-recently-used.  Evicting the lowest ``count`` instead
  would mean a brand-new tag could never establish itself in a full store.
- **Display** is ``count`` desc, ``last_used`` desc, ``text`` asc.  Entries are
  persisted already in display order, so reads are a plain sequential parse.

Format version 2 also persists a bounded context bag per entry and corpus
statistics so ranking can score relation.  Version 1 files still load: their
counts and ``last_used`` stay intact and their bags start empty.

Recording sits on the prompt-submit path, so it is best-effort throughout: any
failure is logged at debug level and swallowed, and a missing, truncated, or
unknown-version file reads as an empty store that the next successful write
replaces.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.config.core import load_merged_config
from sase.core.paths import sase_home
from sase.core.time import generate_timestamp
from sase.history.prompt_store import iter_shard_paths_newest_first, load_shard
from sase.history.prompt_word_index import _PROMPT_WORD_RE

log = logging.getLogger(__name__)

CommonPlaceholderSourceToken = tuple[str, int, int]

_STORE_VERSION = 2
_READABLE_STORE_VERSIONS = frozenset({1, 2})
_DEFAULT_COMMON_PLACEHOLDER_COUNT = 100

# Independent of ``ace.prompt_completion.word_min_length`` (completion offer
# threshold).  Context evidence must keep short topical words such as ``epic``.
CONTEXT_MIN_WORD_LENGTH = 4
CONTEXT_TOKENS_PER_PROMPT = 24
CONTEXT_STOPWORD_RATIO = 0.20
CONTEXT_TOKENS_PER_ENTRY = 24
CONTEXT_VOCABULARY_LIMIT = 2000

# Shards are ``YYMM``, so this bounds the one-time seed at roughly two years of
# history.  A long-lived history must never turn ACE startup into a multi-second
# scan; missing the tail of a very old shard costs at most a few stale tags.
_SEED_SHARD_LIMIT = 24


@dataclass
class _PlaceholderEntry:
    """One saved placeholder, its use count, recency, and context bag."""

    text: str
    count: int
    last_used: str
    context_uses: int = 0
    context: dict[str, int] = field(default_factory=dict)


@dataclass
class _PlaceholderStore:
    """In-memory common-placeholder file: entries plus corpus statistics."""

    entries: list[_PlaceholderEntry]
    prompt_count: int = 0
    context_frequency: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CommonPlaceholderIndex:
    """Loaded common-placeholder store plus corpus statistics for ranking.

    ``_ranking_memo`` is a private mutable slot for the ranking phase.  A warm
    cache rebuild replaces the whole index, so that memo cannot serve a stale
    corpus.
    """

    entries: tuple[_PlaceholderEntry, ...]
    prompt_count: int
    context_frequency: dict[str, int]
    max_count: int
    _ranking_memo: object | None = None


def _common_placeholder_store_file() -> Path:
    """Return the common-placeholder store path."""
    return sase_home() / "prompt_placeholders.json"


def _common_placeholder_lock_file() -> Path:
    """Return the lock file guarding common-placeholder read/modify/write cycles."""
    return sase_home() / "prompt_placeholders.lock"


def _common_placeholder_limit() -> int:
    """Return the configured cap on retained common placeholders.

    Reads ``ace.prompt_completion.common_placeholder_count`` through the cached
    merged config, so the prompt-submit path does no extra disk I/O.  A missing,
    unreadable, or unparsable value falls back to the default; ``0`` disables
    the feature entirely.
    """
    try:
        ace = _config_section(load_merged_config(), "ace")
        raw = _config_section(ace, "prompt_completion").get(
            "common_placeholder_count",
            _DEFAULT_COMMON_PLACEHOLDER_COUNT,
        )
    except Exception:
        log.debug("common placeholder limit unavailable", exc_info=True)
        return _DEFAULT_COMMON_PLACEHOLDER_COUNT
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_COMMON_PLACEHOLDER_COUNT
    return max(0, parsed)


def _config_section(data: object, key: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    section = data.get(key)
    return section if isinstance(section, dict) else {}


def record_prompt_placeholders(text: str) -> None:
    """Record every placeholder written in *text*, best-effort.

    A tag repeated within one prompt counts once: the count measures how many
    prompts used the tag, not how many times it was typed.  Recording never
    raises and never blocks the caller's prompt from being submitted.
    """
    try:
        limit = _common_placeholder_limit()
        if limit <= 0:
            return
        texts = _placeholder_texts(text)
        if not texts:
            return
        timestamp = generate_timestamp()
        with _locked_placeholder_store():
            loaded = _load_store()
            tokens = _prompt_context_tokens(
                text,
                context_frequency=loaded.context_frequency,
                prompt_count=loaded.prompt_count,
            )
            _record_prompt_context(loaded, tokens)
            _apply_uses(loaded.entries, texts, timestamp, tokens)
            _save_payload(_retained(loaded, limit))
    except Exception:
        log.debug("recording common placeholders failed", exc_info=True)


def load_common_placeholder_index() -> CommonPlaceholderIndex:
    """Return the saved placeholders plus corpus statistics.

    A missing, empty, corrupt, or unknown-version store yields an empty index.
    Version 1 files load with empty bags and zero corpus statistics.
    """
    loaded = _load_store()
    entries = tuple(
        _PlaceholderEntry(
            text=entry.text,
            count=entry.count,
            last_used=entry.last_used,
            context_uses=entry.context_uses,
            context=dict(entry.context),
        )
        for entry in loaded.entries
    )
    return CommonPlaceholderIndex(
        entries=entries,
        prompt_count=loaded.prompt_count,
        context_frequency=dict(loaded.context_frequency),
        max_count=max((entry.count for entry in entries), default=0),
    )


def load_common_placeholders(
    limit: int,
    *,
    index: CommonPlaceholderIndex | None = None,
) -> list[str]:
    """Return up to *limit* saved placeholders in display order.

    A missing, empty, corrupt, or unknown-version store yields ``[]``.  The
    file is written already sorted, so no re-ranking happens here.  Pass a
    warm *index* to derive the same list without another disk read.
    """
    if limit <= 0:
        return []
    loaded = index if index is not None else load_common_placeholder_index()
    return [entry.text for entry in loaded.entries[:limit]]


def remove_common_placeholder(text: str) -> bool:
    """Remove the exact saved placeholder *text*, returning whether it existed.

    Corpus statistics stay put: deleting one saved tag does not un-observe the
    prompts the vocabulary was measured over.
    """
    with _locked_placeholder_store():
        loaded = _load_store()
        remaining = [entry for entry in loaded.entries if entry.text != text]
        if len(remaining) == len(loaded.entries):
            return False
        loaded.entries = remaining
        _save_payload(loaded)
    return True


def common_placeholder_source_token() -> CommonPlaceholderSourceToken:
    """Return a cheap staleness token for the store file.

    Mirrors ``prompt_word_index._shard_token`` so a warm cache can skip a rebuild
    that would produce the same list.  An absent store yields a sentinel that
    still differs from any real stat.
    """
    path = _common_placeholder_store_file()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def seed_common_placeholders_from_history(limit: int) -> bool:
    """Seed or upgrade the store from prompt history.

    Returns ``True`` when a store was written (even an empty one, which records
    that the seed has run), and ``False`` when the store is already version 2,
    the feature is disabled, or the scan failed.

    A missing file is a first-run seed.  A version 1 file is upgraded in place:
    existing ``count`` and ``last_used`` stay authoritative, context bags and
    corpus statistics come from the scan, and texts the scan finds that the
    store lacks are added as ordinary seed entries.  A submit that races the
    upgrade is re-read and merged so its recorded use cannot be lost.
    """
    if limit <= 0:
        return False
    path = _common_placeholder_store_file()
    upgrade = False
    if path.exists():
        if _store_file_version(path) != 1:
            return False
        upgrade = True

    try:
        seeded = _seed_store_from_history()
        with _locked_placeholder_store():
            # Another process may have written the store while this scan ran.
            if upgrade:
                current = _load_store()
                _save_payload(_retained(_merge_seed_into_store(current, seeded), limit))
                return True
            if _common_placeholder_store_file().exists():
                return False
            _save_payload(_retained(seeded, limit))
        return True
    except Exception:
        log.debug("seeding common placeholders failed", exc_info=True)
        return False


def prompt_context_tokens(
    text: str,
    *,
    context_frequency: Mapping[str, int],
    prompt_count: int,
) -> tuple[str, ...]:
    """Return this prompt's bounded context tokens for recording and ranking.

    Tag tokens (the literal ``<text>`` spelling of every distinct placeholder,
    raw and literal-zone alike) come first.  Prose tokens are casefolded
    ``_PROMPT_WORD_RE`` matches of at least ``CONTEXT_MIN_WORD_LENGTH``, minus
    stopwords whose ``df / prompt_count`` exceeds ``CONTEXT_STOPWORD_RATIO``.
    The remainder is filled with the rarest prose tokens, ties broken by token
    text, up to ``CONTEXT_TOKENS_PER_PROMPT``.

    Ranking queries use this same function so evidence and queries cannot drift.
    """
    tag_tokens = tuple(
        sorted(_tag_token(inner) for inner in _all_placeholder_texts(text))
    )
    if len(tag_tokens) >= CONTEXT_TOKENS_PER_PROMPT:
        return tag_tokens[:CONTEXT_TOKENS_PER_PROMPT]

    prose: dict[str, None] = {}
    for match in _PROMPT_WORD_RE.finditer(text):
        token = match.group(0).casefold()
        if len(token) < CONTEXT_MIN_WORD_LENGTH:
            continue
        df = context_frequency.get(token, 0)
        if prompt_count > 0 and df / prompt_count > CONTEXT_STOPWORD_RATIO:
            continue
        prose.setdefault(token, None)

    remaining = CONTEXT_TOKENS_PER_PROMPT - len(tag_tokens)
    ranked = sorted(prose, key=lambda token: (context_frequency.get(token, 0), token))
    return tag_tokens + tuple(ranked[:remaining])


# Recording and tests keep the private name; ranking imports the public one.
_prompt_context_tokens = prompt_context_tokens


def _seed_store_from_history() -> _PlaceholderStore:
    """Accumulate placeholder counts and context from the newest shards."""
    by_text: dict[str, _PlaceholderEntry] = {}
    loaded = _PlaceholderStore(entries=[])
    for index, path in enumerate(iter_shard_paths_newest_first()):
        if index >= _SEED_SHARD_LIMIT:
            break
        for entry in load_shard(path):
            texts = _placeholder_texts(entry.text)
            if not texts:
                continue
            tokens = _prompt_context_tokens(
                entry.text,
                context_frequency=loaded.context_frequency,
                prompt_count=loaded.prompt_count,
            )
            _record_prompt_context(loaded, tokens)
            for text in texts:
                existing = by_text.get(text)
                if existing is None:
                    existing = _PlaceholderEntry(
                        text=text,
                        count=1,
                        last_used=entry.last_used,
                    )
                    by_text[text] = existing
                else:
                    existing.count += 1
                    existing.last_used = max(existing.last_used, entry.last_used)
                _add_context(existing, tokens)
    _trim_vocabulary(loaded)
    loaded.entries = list(by_text.values())
    return loaded


def _merge_seed_into_store(
    current: _PlaceholderStore,
    seeded: _PlaceholderStore,
) -> _PlaceholderStore:
    """Keep on-disk counts and timestamps; take context from *seeded*."""
    by_text = {entry.text: entry for entry in current.entries}
    for seed in seeded.entries:
        existing = by_text.get(seed.text)
        if existing is None:
            by_text[seed.text] = _PlaceholderEntry(
                text=seed.text,
                count=seed.count,
                last_used=seed.last_used,
                context_uses=seed.context_uses,
                context=dict(seed.context),
            )
            continue
        existing.context_uses = seed.context_uses
        existing.context = dict(seed.context)
    return _PlaceholderStore(
        entries=list(by_text.values()),
        prompt_count=seeded.prompt_count,
        context_frequency=dict(seeded.context_frequency),
    )


def _placeholder_spans(text: str) -> tuple[Any, ...]:
    from sase.xprompt.placeholder_completion import placeholder_spans

    return placeholder_spans(text)


def _placeholder_texts(text: str) -> tuple[str, ...]:
    """Return the distinct inner texts of every raw placeholder in *text*."""
    seen: dict[str, None] = {}
    for span in _placeholder_spans(text):
        if span.text and span.raw:
            seen.setdefault(span.text, None)
    return tuple(seen)


def _all_placeholder_texts(text: str) -> tuple[str, ...]:
    """Return distinct inner texts of every placeholder, including literal zones."""
    seen: dict[str, None] = {}
    for span in _placeholder_spans(text):
        if span.text:
            seen.setdefault(span.text, None)
    return tuple(seen)


def _tag_token(text: str) -> str:
    return f"<{text}>"


def _apply_uses(
    entries: list[_PlaceholderEntry],
    texts: tuple[str, ...],
    timestamp: str,
    tokens: tuple[str, ...],
) -> None:
    """Increment *texts* in place, inserting unseen ones with ``count`` 1."""
    by_text = {entry.text: entry for entry in entries}
    for text in texts:
        existing = by_text.get(text)
        if existing is None:
            existing = _PlaceholderEntry(text=text, count=1, last_used=timestamp)
            entries.append(existing)
            by_text[text] = existing
        else:
            existing.count += 1
            existing.last_used = timestamp
        _add_context(existing, tokens)


def _add_context(entry: _PlaceholderEntry, tokens: tuple[str, ...]) -> None:
    """Record one prompt's context into *entry*, excluding its own tag token."""
    entry.context_uses += 1
    own = _tag_token(entry.text)
    for token in tokens:
        if token == own:
            continue
        entry.context[token] = entry.context.get(token, 0) + 1
    _trim_entry_context(entry)


def _record_prompt_context(
    loaded: _PlaceholderStore,
    tokens: tuple[str, ...],
) -> None:
    loaded.prompt_count += 1
    for token in tokens:
        loaded.context_frequency[token] = loaded.context_frequency.get(token, 0) + 1
    _trim_vocabulary(loaded)


def _trim_entry_context(entry: _PlaceholderEntry) -> None:
    """Keep the highest-count tokens; ties evict the largest token."""
    if len(entry.context) <= CONTEXT_TOKENS_PER_ENTRY:
        return
    before = len(entry.context)
    keep = sorted(entry.context, key=lambda token: (-entry.context[token], token))
    keep = keep[:CONTEXT_TOKENS_PER_ENTRY]
    entry.context = {token: entry.context[token] for token in keep}
    log.debug(
        "trimmed placeholder context bag for %r from %d to %d tokens",
        entry.text,
        before,
        len(entry.context),
    )


def _trim_vocabulary(loaded: _PlaceholderStore) -> None:
    """Keep the highest-df tokens; ties evict the largest token."""
    frequency = loaded.context_frequency
    if len(frequency) <= CONTEXT_VOCABULARY_LIMIT:
        return
    before = len(frequency)
    keep = sorted(frequency, key=lambda token: (-frequency[token], token))
    keep = keep[:CONTEXT_VOCABULARY_LIMIT]
    loaded.context_frequency = {token: frequency[token] for token in keep}
    log.debug(
        "trimmed placeholder context vocabulary from %d to %d tokens",
        before,
        len(loaded.context_frequency),
    )


def _display_order(entries: list[_PlaceholderEntry]) -> list[_PlaceholderEntry]:
    """Sort by ``count`` desc, then ``last_used`` desc, then ``text`` asc."""
    ordered = sorted(entries, key=lambda entry: entry.text)
    ordered.sort(key=lambda entry: entry.last_used, reverse=True)
    ordered.sort(key=lambda entry: entry.count, reverse=True)
    return ordered


def _retained(loaded: _PlaceholderStore, limit: int) -> _PlaceholderStore:
    """Return the *limit* most recently used entries, in display order."""
    loaded.entries = _retained_entries(loaded.entries, limit)
    return loaded


def _retained_entries(
    entries: list[_PlaceholderEntry],
    limit: int,
) -> list[_PlaceholderEntry]:
    ordered = _display_order(entries)
    if len(ordered) <= limit:
        return ordered
    # Eviction is LRU, not count-based: dropping the lowest count would make a
    # brand-new tag the first candidate for eviction forever.
    by_recency = sorted(ordered, key=lambda entry: entry.last_used, reverse=True)
    return _display_order(by_recency[:limit])


@contextmanager
def _locked_placeholder_store() -> Iterator[None]:
    """Hold an exclusive lock for common-placeholder read/modify/write cycles.

    A dedicated lock file keeps placeholder writes from contending with
    prompt-history writes, which happen on the same submit path.
    """
    lock_file = _common_placeholder_lock_file()
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _entry_from_json(value: object) -> _PlaceholderEntry | None:
    if not isinstance(value, dict):
        return None
    text = value.get("text")
    count = value.get("count")
    last_used = value.get("last_used")
    if not isinstance(text, str) or not text:
        return None
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return None
    if not isinstance(last_used, str):
        return None
    return _PlaceholderEntry(
        text=text,
        count=count,
        last_used=last_used,
        context_uses=_nonneg_int(value.get("context_uses")),
        context=_token_counts(value.get("context")),
    )


def _entries_from_data(data: object) -> list[_PlaceholderEntry]:
    if (
        not isinstance(data, dict)
        or data.get("version") not in _READABLE_STORE_VERSIONS
    ):
        return []
    placeholders = data.get("placeholders")
    if not isinstance(placeholders, list):
        return []
    return [
        entry
        for entry in (_entry_from_json(item) for item in placeholders)
        if entry is not None
    ]


def _nonneg_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _token_counts(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not key:
            continue
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
            continue
        counts[key] = raw
    return counts


def _store_file_version(path: Path) -> int | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        return None
    return version


def _load_store() -> _PlaceholderStore:
    """Load the store, treating any unusable file as empty."""
    path = _common_placeholder_store_file()
    if not path.exists():
        return _PlaceholderStore(entries=[])
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _PlaceholderStore(entries=[])
    entries = _entries_from_data(data)
    if (
        not isinstance(data, dict)
        or data.get("version") not in _READABLE_STORE_VERSIONS
    ):
        return _PlaceholderStore(entries=[])
    if not isinstance(data.get("placeholders"), list):
        return _PlaceholderStore(entries=[])
    if data.get("version") != 2:
        return _PlaceholderStore(entries=entries)
    return _PlaceholderStore(
        entries=entries,
        prompt_count=_nonneg_int(data.get("prompt_count")),
        context_frequency=_token_counts(data.get("context_frequency")),
    )


def _save_payload(loaded: _PlaceholderStore) -> None:
    """Atomically replace the store with *loaded*, entries already in display order."""
    path = _common_placeholder_store_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": _STORE_VERSION,
        "prompt_count": loaded.prompt_count,
        "context_frequency": dict(sorted(loaded.context_frequency.items())),
        "placeholders": [
            {
                "text": entry.text,
                "count": entry.count,
                "last_used": entry.last_used,
                "context_uses": entry.context_uses,
                "context": dict(sorted(entry.context.items())),
            }
            for entry in loaded.entries
        ],
    }
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=f".{os.getpid()}.tmp",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except OSError:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise
