"""Persistent attempt cursors and invocation records for fakey scenarios."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _atomic_json_write(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


@contextmanager
def _locked(state_dir: Path) -> Iterator[None]:
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / ".fakey.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def reserve_invocation(state_dir: Path, state_key: str) -> tuple[int, int]:
    """Atomically advance a scenario cursor and reserve an invocation filename."""

    cursor_path = state_dir / f".fakey-state-{state_key}.json"
    counter_path = state_dir / ".fakey-invocations.json"
    with _locked(state_dir):
        cursor = _read_json(cursor_path)
        attempt_index = int(cursor.get("next_attempt", 0))
        _atomic_json_write(cursor_path, {"next_attempt": attempt_index + 1})

        counter = _read_json(counter_path)
        invocation_number = int(counter.get("next_invocation", 1))
        _atomic_json_write(counter_path, {"next_invocation": invocation_number + 1})
    return attempt_index, invocation_number


def write_invocation(
    state_dir: Path, invocation_number: int, record: Mapping[str, Any]
) -> Path:
    """Write the final record for a previously reserved invocation."""

    path = state_dir / f"invocation-{invocation_number}.json"
    _atomic_json_write(path, record)
    return path
