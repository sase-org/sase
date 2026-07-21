"""Load-balanced model-alias pool parsing, availability, and rotation state.

Alias values may opt into a round-robin pool with ``|`` separators.  This
module deliberately knows nothing about alias-chain resolution: callers pass
the already-resolved provider/model target for each member when asking about
availability, then select from the resulting boolean mask.

Rotation state is machine-global and best-effort.  A missing, corrupt, locked,
or otherwise unreadable state file always behaves like a fresh rotation; an
LLM launch must never fail merely because usage accounting could not be saved.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from sase.core.paths import sase_home

_STATE_FILENAME = "llm_lb.json"
_LOCK_FILENAME = "llm_lb.lock"
_STATE_VERSION = 1


class ModelAliasPoolError(ValueError):
    """Raised when a pipe-separated alias value has invalid pool syntax."""


@dataclass(frozen=True, slots=True)
class ModelAliasPool:
    """A normalized, non-empty sequence of alias-pool members."""

    members: tuple[str, ...]

    @property
    def normalized(self) -> str:
        """Return the canonical display/fingerprint spelling for this pool."""
        return " | ".join(self.members)

    @property
    def fingerprint(self) -> str:
        """Return a stable fingerprint that changes whenever membership does."""
        payload = json.dumps(self.members, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_model_alias_pool(value: str) -> ModelAliasPool | None:
    """Parse *value* when it contains pool syntax, otherwise return ``None``.

    Whitespace around members is ignored.  Leading, trailing, or consecutive
    separators are rejected rather than silently discarding an empty member.
    A value without ``|`` retains the historical single-target behavior.
    """
    if "|" not in value:
        return None
    members = tuple(part.strip() for part in value.split("|"))
    if any(not member for member in members):
        raise ModelAliasPoolError(
            "load-balanced alias pools cannot contain empty members; remove "
            "leading, trailing, or consecutive '|' separators"
        )
    return ModelAliasPool(members)


def _state_path() -> Path:
    """Return the lazily-resolved machine-global rotation state path."""
    return sase_home() / _STATE_FILENAME


@contextmanager
def _locked_state() -> Iterator[None]:
    """Serialize state reads and read/modify/write cursor updates."""
    lock_path = sase_home() / _LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically replace *path* with a JSON representation of *data*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _delete_state_best_effort() -> None:
    try:
        _state_path().unlink()
    except (FileNotFoundError, OSError):
        pass


def _read_entries_unlocked() -> tuple[dict[str, dict[str, Any]], bool]:
    """Return valid cursor entries and whether corrupt data was discarded."""
    try:
        raw = _state_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, False
    except OSError:
        return {}, False
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        _delete_state_best_effort()
        return {}, True
    if not isinstance(data, dict) or data.get("version") != _STATE_VERSION:
        _delete_state_best_effort()
        return {}, True
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, dict):
        _delete_state_best_effort()
        return {}, True

    entries: dict[str, dict[str, Any]] = {}
    changed = set(data) - {"version", "entries"} != set()
    for alias, raw_entry in raw_entries.items():
        if not isinstance(alias, str) or not isinstance(raw_entry, dict):
            changed = True
            continue
        stored_alias = raw_entry.get("alias")
        fingerprint = raw_entry.get("fingerprint")
        cursor = raw_entry.get("cursor")
        if (
            stored_alias != alias
            or not isinstance(fingerprint, str)
            or isinstance(cursor, bool)
            or not isinstance(cursor, int)
            or cursor < 0
        ):
            changed = True
            continue
        entries[alias] = {
            "alias": alias,
            "fingerprint": fingerprint,
            "cursor": cursor,
        }
        if set(raw_entry) != {"alias", "fingerprint", "cursor"}:
            changed = True
    return entries, changed or len(entries) != len(raw_entries)


def _write_entries_unlocked(entries: dict[str, dict[str, Any]]) -> None:
    if not entries:
        _delete_state_best_effort()
        return
    _atomic_write_json(_state_path(), {"version": _STATE_VERSION, "entries": entries})


def _selection_index(cursor: int, availability: Sequence[bool]) -> int:
    """Return the first available index at/after *cursor*, wrapping once."""
    size = len(availability)
    if size == 0:
        raise ValueError("load-balanced alias pool is empty")
    effective = availability if any(availability) else [True] * size
    for offset in range(size):
        index = (cursor + offset) % size
        if effective[index]:
            return index
    return 0  # defensive; the all-false case is replaced above


def select_model_alias_pool_member(
    alias: str,
    pool: ModelAliasPool,
    availability: Sequence[bool],
    *,
    consume: bool = False,
) -> int:
    """Return the selected member index, optionally advancing its cursor.

    The cursor is keyed by the alias that owns the pool.  A pool fingerprint
    mismatch resets selection to member zero.  When every member is unavailable
    the unfiltered pool is retained, allowing normal provider diagnostics to
    explain why the selected launch cannot run.
    """
    if len(availability) != len(pool.members):
        raise ValueError("availability mask does not match alias pool")
    cleaned_alias = alias.strip()
    if not cleaned_alias:
        raise ValueError("load-balanced alias owner is empty")

    try:
        with _locked_state():
            entries, changed = _read_entries_unlocked()
            entry = entries.get(cleaned_alias)
            cursor = 0
            if entry is not None and entry.get("fingerprint") == pool.fingerprint:
                cursor = int(entry["cursor"])
            index = _selection_index(cursor, availability)
            if consume:
                entries[cleaned_alias] = {
                    "alias": cleaned_alias,
                    "fingerprint": pool.fingerprint,
                    "cursor": (index + 1) % len(pool.members),
                }
                _write_entries_unlocked(entries)
            elif changed:
                _write_entries_unlocked(entries)
            return index
    except Exception:
        # Cursor accounting is advisory.  Resolution and launch diagnostics are
        # more important than surfacing a state-file/lock failure here.
        return _selection_index(0, availability)
