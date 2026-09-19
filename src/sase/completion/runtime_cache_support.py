"""Filesystem and hashing primitives for the runtime grammar cache."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sase.completion.runtime_cache_models import CompletionCacheError
from sase.core.paths import sase_subdir

LOCK_TIMEOUT_SECONDS = 10.0
_RUNTIME_CACHE_KEEP = 6


@contextmanager
def bounded_lock(path: Path) -> Iterator[None]:
    """Acquire a cache lock, failing after a short bounded wait."""
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    with path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise CompletionCacheError(
                        f"timed out waiting for completion cache lock: {path}"
                    ) from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def cache_root() -> Path:
    return sase_subdir("completion") / "grammar"


def shell_cache_dir(runtime_key: str, shell: str) -> Path:
    return cache_root() / runtime_key / shell


def grammar_filename(shell: str) -> str:
    names = {"bash": "sase.bash", "fish": "sase.fish", "zsh": "_sase"}
    try:
        return names[shell]
    except KeyError:
        raise CompletionCacheError(f"unsupported shell: {shell}") from None


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def digest_json(data: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prune_old_runtime_dirs(root: Path) -> None:
    try:
        entries = [path for path in root.iterdir() if path.is_dir()]
    except OSError:
        return
    if len(entries) <= _RUNTIME_CACHE_KEEP:
        return
    entries.sort(key=_mtime, reverse=True)
    for stale in entries[_RUNTIME_CACHE_KEEP:]:
        remove_tree(stale)


def remove_tree(path: Path) -> None:
    for child in sorted(
        path.rglob("*"), key=lambda item: len(item.parts), reverse=True
    ):
        try:
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        pass


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0
