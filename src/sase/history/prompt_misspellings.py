"""Durable store of words ``K`` has proven misspelled in the prompt input.

Every ``K`` press that reaches ``aspell`` and comes back ``misspelled`` teaches
this store a new word; the prompt input then underlines that word wherever it
reappears, forever, without ever running ``aspell`` again. ``allowed`` is the
escape hatch: accepting a word removes it from ``misspelled`` and remembers the
decision so the next ``K`` on that word does not immediately re-flag it.

Membership and dedupe are casefolded, but the stored spelling is whichever
casing was first seen for that key. Recording sits on the ``K`` result path, so
it is best-effort throughout: a failure is logged at debug level and swallowed,
and a missing, truncated, or version-mismatched file reads as empty sets that
the next successful write replaces.
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

log = logging.getLogger(__name__)

MisspellingsSourceToken = tuple[str, int, int]

_STORE_VERSION = 1
_DEFAULT_MAX_REMEMBERED_WORDS = 5000


@dataclass(frozen=True, slots=True)
class _MisspellingSets:
    """Casefold-deduped misspelled and allowed words, in insertion order."""

    misspelled: tuple[str, ...]
    allowed: tuple[str, ...]


def _misspellings_store_file() -> Path:
    """Return the misspellings store path."""
    return sase_home() / "prompt_misspellings.json"


def _misspellings_lock_file() -> Path:
    """Return the lock file guarding misspellings read/modify/write cycles."""
    return sase_home() / "prompt_misspellings.lock"


def _misspellings_limit() -> int:
    """Return the configured cap on each retained word list.

    Reads ``ace.prompt_spellcheck.max_remembered_words`` through the cached
    merged config. A missing, unreadable, or unparsable value falls back to the
    default; ``0`` or lower disables retention entirely.
    """
    try:
        ace = _config_section(load_merged_config(), "ace")
        raw = _config_section(ace, "prompt_spellcheck").get(
            "max_remembered_words",
            _DEFAULT_MAX_REMEMBERED_WORDS,
        )
    except Exception:
        log.debug("misspellings limit unavailable", exc_info=True)
        return _DEFAULT_MAX_REMEMBERED_WORDS
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_REMEMBERED_WORDS
    return max(0, parsed)


def _config_section(data: object, key: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    section = data.get(key)
    return section if isinstance(section, dict) else {}


def load_misspellings() -> _MisspellingSets:
    """Load the store, treating any unusable file as empty."""
    return _load_payload()


def record_misspelling(word: str) -> bool:
    """Persist *word* as misspelled, returning whether the store changed.

    A no-op when *word* casefolds to an entry already in ``misspelled`` or
    ``allowed`` -- accepting a word must not be undone by the next lookup.
    Never raises; failures log at debug and leave the store untouched.
    """
    key = word.casefold()
    if not key:
        return False
    try:
        limit = _misspellings_limit()
        if limit <= 0:
            return False
        with _locked_misspellings_store():
            misspelled, allowed = _load_lists()
            if key in _casefold_keys(allowed) or key in _casefold_keys(misspelled):
                return False
            _save_lists(_trimmed([*misspelled, word], limit), allowed)
        return True
    except Exception:
        log.debug("recording prompt misspelling failed", exc_info=True)
        return False


def allow_word(word: str) -> bool:
    """Move *word* from ``misspelled`` into ``allowed``, best-effort."""
    key = word.casefold()
    if not key:
        return False
    try:
        with _locked_misspellings_store():
            misspelled, allowed = _load_lists()
            remaining = [w for w in misspelled if w.casefold() != key]
            already_allowed = key in _casefold_keys(allowed)
            if remaining == misspelled and already_allowed:
                return False
            limit = _misspellings_limit()
            next_allowed = (
                allowed
                if already_allowed
                else _trimmed([*allowed, word], limit)
                if limit > 0
                else allowed
            )
            _save_lists(remaining, next_allowed)
        return True
    except Exception:
        log.debug("allowing prompt misspelling failed", exc_info=True)
        return False


def forget_misspelling(word: str) -> bool:
    """Remove *word* from ``misspelled`` only, returning whether it existed."""
    key = word.casefold()
    if not key:
        return False
    try:
        with _locked_misspellings_store():
            misspelled, allowed = _load_lists()
            remaining = [w for w in misspelled if w.casefold() != key]
            if len(remaining) == len(misspelled):
                return False
            _save_lists(remaining, allowed)
        return True
    except Exception:
        log.debug("forgetting prompt misspelling failed", exc_info=True)
        return False


def misspellings_source_token() -> MisspellingsSourceToken:
    """Return a cheap staleness token for the store file."""
    path = _misspellings_store_file()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _casefold_keys(words: list[str]) -> set[str]:
    return {word.casefold() for word in words}


def _dedupe_casefold(words: list[str]) -> list[str]:
    """Keep the first-seen spelling for each casefolded key, in order."""
    seen: dict[str, str] = {}
    for word in words:
        seen.setdefault(word.casefold(), word)
    return list(seen.values())


def _trimmed(words: list[str], limit: int) -> list[str]:
    """Dedupe, then keep the newest *limit* entries, trimming oldest-first."""
    deduped = _dedupe_casefold(words)
    if limit <= 0:
        return []
    if len(deduped) <= limit:
        return deduped
    return deduped[-limit:]


@contextmanager
def _locked_misspellings_store() -> Iterator[None]:
    """Hold an exclusive lock for misspellings read/modify/write cycles."""
    lock_file = _misspellings_lock_file()
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _load_lists() -> tuple[list[str], list[str]]:
    sets = _load_payload()
    return list(sets.misspelled), list(sets.allowed)


def _load_payload() -> _MisspellingSets:
    path = _misspellings_store_file()
    if not path.exists():
        return _MisspellingSets(misspelled=(), allowed=())
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _MisspellingSets(misspelled=(), allowed=())
    if not isinstance(data, dict) or data.get("version") != _STORE_VERSION:
        return _MisspellingSets(misspelled=(), allowed=())
    return _MisspellingSets(
        misspelled=tuple(_dedupe_casefold(_string_list(data.get("misspelled")))),
        allowed=tuple(_dedupe_casefold(_string_list(data.get("allowed")))),
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _save_lists(misspelled: list[str], allowed: list[str]) -> None:
    """Atomically replace the store with *misspelled* and *allowed*."""
    path = _misspellings_store_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": _STORE_VERSION,
        "misspelled": misspelled,
        "allowed": allowed,
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


__all__ = [
    "MisspellingsSourceToken",
    "allow_word",
    "forget_misspelling",
    "load_misspellings",
    "misspellings_source_token",
    "record_misspelling",
]
