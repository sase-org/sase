"""Persistent state helpers for runner-owned chop policy bookkeeping."""

from __future__ import annotations

import fcntl
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sase.core.axe_chop_facade import CHOP_STATE_SCHEMA_VERSION

from .state import atomic_write_json, ensure_chop_dirs, read_json

_DEFAULT_CHECKPOINT_DOCUMENT: dict[str, Any] = {
    "schema_version": CHOP_STATE_SCHEMA_VERSION,
    "entries": {},
}
_DEFAULT_SEEN_DOCUMENT: dict[str, Any] = {
    "schema_version": CHOP_STATE_SCHEMA_VERSION,
    "entries": [],
}


def checkpoint_path(lumberjack_name: str, chop_name: str) -> Path:
    return ensure_chop_dirs(lumberjack_name, chop_name) / "checkpoint.json"


def seen_path(lumberjack_name: str, chop_name: str) -> Path:
    return ensure_chop_dirs(lumberjack_name, chop_name) / "seen.json"


def _lock_path(lumberjack_name: str, chop_name: str) -> Path:
    return ensure_chop_dirs(lumberjack_name, chop_name) / "policy.lock"


@contextmanager
def chop_policy_lock(lumberjack_name: str, chop_name: str) -> Iterator[None]:
    with _lock_path(lumberjack_name, chop_name).open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def read_checkpoint_document(lumberjack_name: str, chop_name: str) -> dict[str, Any]:
    return read_policy_document(
        checkpoint_path(lumberjack_name, chop_name),
        _DEFAULT_CHECKPOINT_DOCUMENT,
        "checkpoint",
    )


def read_seen_document(lumberjack_name: str, chop_name: str) -> dict[str, Any]:
    return read_policy_document(
        seen_path(lumberjack_name, chop_name),
        _DEFAULT_SEEN_DOCUMENT,
        "seen-store",
    )


def read_policy_document(
    path: Path,
    default: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default))
    document = read_json(path)
    if not isinstance(document, dict):
        raise ValueError(f"{label} state is unreadable: {path}")
    return document


__all__ = [
    "atomic_write_json",
    "checkpoint_path",
    "chop_policy_lock",
    "read_checkpoint_document",
    "read_policy_document",
    "read_seen_document",
    "seen_path",
]
