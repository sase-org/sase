"""Durable suppression store for deleted prompt-history words."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from sase.core.paths import sase_home

PromptWordDeletionsSourceToken = tuple[str, int, int]

_STORE_VERSION = 1
_MAX_DELETED_WORDS = 10_000


def _prompt_word_deletions_store_file() -> Path:
    """Return the deleted-history-word store path."""
    return sase_home() / "prompt_word_deletions.json"


def load_deleted_prompt_words() -> set[str]:
    """Return exact-spelling history words suppressed by the user."""
    return set(_load_words())


def delete_prompt_word(word: str) -> bool:
    """Persist *word* as deleted, returning whether the store changed."""
    words = _load_words()
    if word in words:
        return False
    words.append(word)
    if len(words) > _MAX_DELETED_WORDS:
        words = words[-_MAX_DELETED_WORDS:]
    _save_words(words)
    return True


def prompt_word_deletions_source_token() -> PromptWordDeletionsSourceToken:
    """Return a cheap staleness token for the deletion store."""
    path = _prompt_word_deletions_store_file()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _load_words() -> list[str]:
    """Load valid words in oldest-to-newest order, deduplicated."""
    path = _prompt_word_deletions_store_file()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or data.get("version") != _STORE_VERSION:
        return []
    raw_words = data.get("words")
    if not isinstance(raw_words, list):
        return []
    return list(dict.fromkeys(word for word in raw_words if isinstance(word, str)))


def _save_words(words: list[str]) -> None:
    """Atomically replace the deletion store with *words*."""
    path = _prompt_word_deletions_store_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=f".{os.getpid()}.tmp",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": _STORE_VERSION, "words": words}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except OSError:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise
