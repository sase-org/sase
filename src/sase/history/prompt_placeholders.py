"""Durable store of common ``<placeholder>`` tags written in prompts.

Every placeholder the user writes is recorded here so the ``<`` completion
menu can offer tags from earlier prompts beneath the ones found in the prompt
being edited.  The store is deliberately authoritative rather than derived
from prompt history on every read: ranking needs a use count over *all*
history, and short prompts that never enter prompt history still contribute
their tags.  Prompt history is consulted exactly once, as a best-effort seed
(:func:`seed_common_placeholders_from_history`) when the store file is absent.

Two orderings are in play and they are not the same:

- **Retention** is least-recently-used.  Evicting the lowest ``count`` instead
  would mean a brand-new tag could never establish itself in a full store.
- **Display** is ``count`` desc, ``last_used`` desc, ``text`` asc.  Entries are
  persisted already in display order, so reads are a plain sequential parse.

Recording sits on the prompt-submit path, so it is best-effort throughout: any
failure is logged at debug level and swallowed, and a missing, truncated, or
version-mismatched file reads as an empty store that the next successful write
replaces.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.config.core import load_merged_config
from sase.core.paths import sase_home
from sase.core.time import generate_timestamp
from sase.history.prompt_store import iter_shard_paths_newest_first, load_shard

log = logging.getLogger(__name__)

CommonPlaceholderSourceToken = tuple[str, int, int]

_STORE_VERSION = 1
_DEFAULT_COMMON_PLACEHOLDER_COUNT = 100

# Shards are ``YYMM``, so this bounds the one-time seed at roughly two years of
# history.  A long-lived history must never turn ACE startup into a multi-second
# scan; missing the tail of a very old shard costs at most a few stale tags.
_SEED_SHARD_LIMIT = 24


@dataclass
class _PlaceholderEntry:
    """One saved placeholder, its use count, and when it was last written."""

    text: str
    count: int
    last_used: str


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
            entries = _load_payload()
            _apply_uses(entries, texts, timestamp)
            _save_payload(_retained(entries, limit))
    except Exception:
        log.debug("recording common placeholders failed", exc_info=True)


def load_common_placeholders(limit: int) -> list[str]:
    """Return up to *limit* saved placeholders in display order.

    A missing, empty, corrupt, or version-mismatched store yields ``[]``.  The
    file is written already sorted, so no re-ranking happens here.
    """
    if limit <= 0:
        return []
    return [entry.text for entry in _load_payload()[:limit]]


def remove_common_placeholder(text: str) -> bool:
    """Remove the exact saved placeholder *text*, returning whether it existed."""
    with _locked_placeholder_store():
        entries = _load_payload()
        remaining = [entry for entry in entries if entry.text != text]
        if len(remaining) == len(entries):
            return False
        _save_payload(remaining)
    return True


def common_placeholder_source_token() -> CommonPlaceholderSourceToken:
    """Return a cheap staleness token for the store file.

    Mirrors ``prompt_words._shard_token`` so a warm cache can skip a rebuild
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
    """Seed the store once from prompt history, so day one is already useful.

    Returns ``True`` when a store was written (even an empty one, which records
    that the seed has run), and ``False`` when the store already exists, the
    feature is disabled, or the scan failed.  This is a first-run seed, not a
    repair mechanism for an existing store.
    """
    if limit <= 0:
        return False
    if _common_placeholder_store_file().exists():
        return False

    try:
        entries = _seed_entries_from_history()
        with _locked_placeholder_store():
            # Another process may have written the store while this scan ran;
            # a seed must never clobber recorded uses.
            if _common_placeholder_store_file().exists():
                return False
            _save_payload(_retained(entries, limit))
        return True
    except Exception:
        log.debug("seeding common placeholders failed", exc_info=True)
        return False


def _seed_entries_from_history() -> list[_PlaceholderEntry]:
    """Accumulate placeholder counts from the newest bounded run of shards."""
    by_text: dict[str, _PlaceholderEntry] = {}
    for index, path in enumerate(iter_shard_paths_newest_first()):
        if index >= _SEED_SHARD_LIMIT:
            break
        for entry in load_shard(path):
            for text in _placeholder_texts(entry.text):
                existing = by_text.get(text)
                if existing is None:
                    by_text[text] = _PlaceholderEntry(
                        text=text,
                        count=1,
                        last_used=entry.last_used,
                    )
                    continue
                existing.count += 1
                existing.last_used = max(existing.last_used, entry.last_used)
    return list(by_text.values())


def _placeholder_texts(text: str) -> tuple[str, ...]:
    """Return the distinct inner texts of every raw placeholder in *text*."""
    from sase.xprompt.placeholder_completion import placeholder_spans

    seen: dict[str, None] = {}
    for span in placeholder_spans(text):
        if span.text and span.raw:
            seen.setdefault(span.text, None)
    return tuple(seen)


def _apply_uses(
    entries: list[_PlaceholderEntry],
    texts: tuple[str, ...],
    timestamp: str,
) -> None:
    """Increment *texts* in place, inserting unseen ones with ``count`` 1."""
    by_text = {entry.text: entry for entry in entries}
    for text in texts:
        existing = by_text.get(text)
        if existing is None:
            entry = _PlaceholderEntry(text=text, count=1, last_used=timestamp)
            entries.append(entry)
            by_text[text] = entry
            continue
        existing.count += 1
        existing.last_used = timestamp


def _display_order(entries: list[_PlaceholderEntry]) -> list[_PlaceholderEntry]:
    """Sort by ``count`` desc, then ``last_used`` desc, then ``text`` asc."""
    ordered = sorted(entries, key=lambda entry: entry.text)
    ordered.sort(key=lambda entry: entry.last_used, reverse=True)
    ordered.sort(key=lambda entry: entry.count, reverse=True)
    return ordered


def _retained(
    entries: list[_PlaceholderEntry],
    limit: int,
) -> list[_PlaceholderEntry]:
    """Return the *limit* most recently used entries, in display order."""
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
    return _PlaceholderEntry(text=text, count=count, last_used=last_used)


def _entries_from_data(data: object) -> list[_PlaceholderEntry]:
    if not isinstance(data, dict) or data.get("version") != _STORE_VERSION:
        return []
    placeholders = data.get("placeholders")
    if not isinstance(placeholders, list):
        return []
    return [
        entry
        for entry in (_entry_from_json(item) for item in placeholders)
        if entry is not None
    ]


def _load_payload() -> list[_PlaceholderEntry]:
    """Load the store, treating any unusable file as empty."""
    path = _common_placeholder_store_file()
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return _entries_from_data(data)


def _save_payload(entries: list[_PlaceholderEntry]) -> None:
    """Atomically replace the store with *entries*, already in display order."""
    path = _common_placeholder_store_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": _STORE_VERSION,
        "placeholders": [
            {
                "text": entry.text,
                "count": entry.count,
                "last_used": entry.last_used,
            }
            for entry in entries
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
