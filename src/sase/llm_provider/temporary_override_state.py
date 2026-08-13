"""On-disk state store for temporary, per-alias LLM provider/model overrides.

The state lives at ``~/.sase/llm_override.json`` so all sase processes on the
same machine see the same active overrides. The on-disk schema is versioned:
``{"version": 2, "overrides": {"<alias>": {...}}}``. A legacy v1 flat object (a
single, top-level override) is migrated on read into ``overrides.default`` so an
override set by an older build keeps working. Writes are atomic (temp file +
``os.replace``); reads are best-effort self-cleaning — expired or malformed
entries are pruned and the file is removed once no override remains.

Every mutation here takes the process-shared file lock, so the full
read/modify/write cycle is serialized across sase processes. The user-facing API
built on top of this store lives in :mod:`sase.llm_provider.temporary_override`;
the lock-free display read lives in
:mod:`sase.llm_provider.temporary_override_peek`.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.xprompt.effort import is_valid_effort

from .config import DEFAULT_MODEL_ALIAS_NAME

_STATE_FILENAME = "llm_override.json"
_LOCK_FILENAME = "llm_override.lock"

#: On-disk schema version for the per-alias override state file.
_STATE_VERSION = 2


@dataclass(frozen=True)
class TemporaryLLMOverride:
    """Active temporary default provider/model override."""

    provider: str
    model: str
    raw_model: str
    created_at: float
    expires_at: float | None
    source: str
    effort: str | None = None


def state_path() -> Path:
    """Return the absolute path to the override state file.

    Resolved lazily so ``$SASE_HOME`` and test redirection are honored per-call.
    """
    return sase_home() / _STATE_FILENAME


@contextmanager
def _locked_state() -> Iterator[None]:
    """Serialize state reads that may clean up and all read/modify/write cycles."""
    lock_path = sase_home() / _LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write *data* as JSON to *path* atomically (temp file + replace + fsync)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _delete_state_best_effort() -> None:
    try:
        state_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _read_state_dict() -> dict | None:
    """Read and JSON-parse the state file's top-level object.

    Returns the parsed dict, or ``None`` when the file is missing, unreadable,
    not valid JSON, or not a JSON object. Unparseable / non-object files are
    deleted best-effort so a corrupt file never wedges future launches.
    """
    path = state_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        _delete_state_best_effort()
        return None

    if not isinstance(data, dict):
        _delete_state_best_effort()
        return None
    return data


def extract_raw_entries(data: dict) -> tuple[dict[str, Any] | None, bool]:
    """Split a parsed state dict into ``{alias: entry_dict}`` + a canonical flag.

    Handles both schema versions:

    * **v2** (``{"version": 2, "overrides": {...}}``) — the ``overrides`` map is
      returned directly. ``canonical`` is ``True`` only when the file is already
      in fully canonical v2 form (correct version, a dict of string-keyed
      entries, and no stray top-level keys), so a steady-state read never
      rewrites the file.
    * **v1** (a flat, top-level single override) — migrated in-memory into
      ``{"default": data}`` with ``canonical=False`` so the next write upgrades
      the file to v2.

    Returns ``(None, True)`` when the structure is unrecoverable (a v2 file whose
    ``overrides`` is not a dict), signalling the caller to delete the file.
    """
    if data.get("version") == _STATE_VERSION or "overrides" in data:
        overrides = data.get("overrides")
        if not isinstance(overrides, dict):
            return None, True
        cleaned = {k: v for k, v in overrides.items() if isinstance(k, str)}
        canonical = (
            data.get("version") == _STATE_VERSION
            and len(cleaned) == len(overrides)
            and set(data.keys()) <= {"version", "overrides"}
        )
        return cleaned, canonical

    # Legacy v1 flat object: a single top-level override → overrides.default.
    return {DEFAULT_MODEL_ALIAS_NAME: data}, False


def entry_from_dict(entry: object) -> TemporaryLLMOverride | None:
    """Validate one raw override entry into a :class:`TemporaryLLMOverride`.

    Returns ``None`` for any structurally invalid entry (missing or wrong-typed
    fields) so a single bad entry never crashes a launch. Unknown extra keys
    (for example retired ``pre_override_*`` snapshot keys) are ignored.
    """
    if not isinstance(entry, dict):
        return None
    required = ("provider", "model", "raw_model", "created_at", "source")
    if not all(k in entry for k in required):
        return None
    if not all(
        isinstance(entry[k], str) for k in ("provider", "model", "raw_model", "source")
    ):
        return None
    created_at = entry["created_at"]
    if not _is_finite_number(created_at):
        return None
    expires_at = entry.get("expires_at")
    if expires_at is not None and not _is_finite_number(expires_at):
        return None
    effort = entry.get("effort")
    if effort is not None and (
        not isinstance(effort, str) or not is_valid_effort(effort)
    ):
        return None
    return TemporaryLLMOverride(
        provider=entry["provider"],
        model=entry["model"],
        raw_model=entry["raw_model"],
        created_at=float(created_at),
        expires_at=float(expires_at) if expires_at is not None else None,
        source=entry["source"],
        effort=effort,
    )


def _is_finite_number(value: object) -> bool:
    """Return whether *value* is a finite JSON timestamp number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _serialize_overrides(overrides: dict[str, TemporaryLLMOverride]) -> dict:
    """Render the active override map as the canonical v2 state dict."""
    return {
        "version": _STATE_VERSION,
        "overrides": {alias: asdict(o) for alias, o in overrides.items()},
    }


def _load_active_overrides_unlocked(
    now: float | None = None,
) -> dict[str, TemporaryLLMOverride]:
    """Return the active (non-expired) per-alias overrides, self-cleaning state.

    Performs the v1→v2 read migration, drops invalid/expired entries, and keeps
    the file honest: it deletes the file when no active override remains and
    rewrites it (atomically) whenever the on-disk contents differ from the
    pruned/migrated result. A steady-state read of a canonical file with only
    active entries performs no write.
    """
    data = _read_state_dict()
    if data is None:
        return {}

    raw_entries, canonical = extract_raw_entries(data)
    if raw_entries is None:
        _delete_state_best_effort()
        return {}

    current = time.time() if now is None else now
    active: dict[str, TemporaryLLMOverride] = {}
    changed = not canonical
    for alias, entry in raw_entries.items():
        override = entry_from_dict(entry)
        if override is None:
            changed = True
            continue
        if override.expires_at is not None and current >= override.expires_at:
            changed = True
            continue
        active[alias] = override

    if not active:
        _delete_state_best_effort()
        return {}
    if changed:
        _atomic_write_json(state_path(), _serialize_overrides(active))
    return active


def load_active_overrides(
    now: float | None = None,
) -> dict[str, TemporaryLLMOverride]:
    """Return active overrides while serializing self-cleaning file writes."""
    with _locked_state():
        return _load_active_overrides_unlocked(now)


def store_alias_override(alias: str, override: TemporaryLLMOverride) -> None:
    """Persist *override* under *alias*, preserving every other active override.

    Expired entries are pruned as of the override's own ``created_at`` so a
    single locked read/modify/write cycle both cleans and records.
    """
    with _locked_state():
        overrides = _load_active_overrides_unlocked(now=override.created_at)
        overrides[alias] = override
        _atomic_write_json(state_path(), _serialize_overrides(overrides))


def remove_alias_override(alias: str) -> bool:
    """Drop the stored entry for *alias*, returning whether one was present.

    Removal is by key, so an already-expired entry still reports ``True``. Other
    aliases' overrides are preserved; the file is deleted once empty.
    """
    with _locked_state():
        data = _read_state_dict()
        if data is None:
            return False
        raw_entries, _ = extract_raw_entries(data)
        if raw_entries is None:
            _delete_state_best_effort()
            return False
        if alias not in raw_entries:
            return False

        rebuilt: dict[str, TemporaryLLMOverride] = {}
        for key, entry in raw_entries.items():
            if key == alias:
                continue
            override = entry_from_dict(entry)
            if override is not None:
                rebuilt[key] = override
        if rebuilt:
            _atomic_write_json(state_path(), _serialize_overrides(rebuilt))
        else:
            _delete_state_best_effort()
        return True
