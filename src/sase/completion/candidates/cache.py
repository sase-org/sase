"""Disk cache for pre-argparse completion candidates.

The second of two cache layers: this one absorbs repeated provider calls
across separate ``sase completion candidates`` invocations. The in-shell
layer that absorbs per-keystroke pressure arrives with the ``wire`` epic
phase. ``SASE_COMPLETION_NO_CACHE=1`` bypasses this layer entirely, e.g. for
tests that must observe a fresh provider call every time.
"""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from sase.completion.candidates.protocol import (
    Candidate,
    candidate_from_line,
    candidate_to_line,
)
from sase.core.paths import sase_subdir

DEFAULT_TTL_SECONDS = 30.0
_NO_CACHE_ENV_VAR = "SASE_COMPLETION_NO_CACHE"


def _cache_dir() -> Path:
    return sase_subdir("completion") / "cache"


def _cache_path(cache_key: str) -> Path:
    return _cache_dir() / f"{cache_key}.tsv"


def _cache_disabled() -> bool:
    return os.environ.get(_NO_CACHE_ENV_VAR) == "1"


def load_cached_candidates(
    cache_key: str,
    *,
    source_mtime: float | None,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> list[Candidate] | None:
    """Return cached candidates for *cache_key*, or ``None`` on a cache miss.

    A miss covers a disabled cache, an absent cache file, a cache file older
    than *source_mtime* (the store changed since the cache was written), and
    a cache file older than *ttl_seconds*.
    """
    if _cache_disabled():
        return None
    try:
        cache_mtime = _cache_path(cache_key).stat().st_mtime
    except OSError:
        return None
    if source_mtime is not None and cache_mtime < source_mtime:
        return None
    if time.time() - cache_mtime > ttl_seconds:
        return None
    try:
        text = _cache_path(cache_key).read_text(encoding="utf-8")
    except OSError:
        return None
    return [candidate_from_line(line) for line in text.splitlines() if line]


def store_cached_candidates(cache_key: str, candidates: Sequence[Candidate]) -> None:
    """Best-effort atomic write of *candidates* to the disk cache.

    A write failure (e.g. a read-only home directory) never propagates -- the
    cache is an optimization, not a correctness requirement.
    """
    if _cache_disabled():
        return
    directory = _cache_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=f".{cache_key}.", suffix=".tmp", dir=directory
        )
    except OSError:
        return
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            for candidate in candidates:
                handle.write(candidate_to_line(candidate))
                handle.write("\n")
        os.replace(tmp_name, _cache_path(cache_key))
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "load_cached_candidates",
    "store_cached_candidates",
]
