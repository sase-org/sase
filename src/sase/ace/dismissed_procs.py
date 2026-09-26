"""Persistent tracking of dismissed stand-alone named-proc Agents-tab rows.

Dismissal is host-side ACE inbox state keyed by native proc id. It does not
mutate the durable proc store: dismissed rows stay visible in the Procs pane
and in ``sase proc list`` / ``sase proc show``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Collection
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

from .dismissed_agents_bundles import write_json_file_atomic

SCHEMA_VERSION = 1

_DISMISSED_PROCS_FILE: Path | None = None
# legacy sase-shell spelling: pre-rename tests hook this path.
_DISMISSED_PROC_SHELLS_FILE: Path | None = None
_LOCK = threading.Lock()


def _dismissed_procs_file() -> Path:
    """Return the dismissed-proc JSON path, honoring the test hook."""
    return _DISMISSED_PROCS_FILE or sase_home() / "dismissed_procs.json"


def _legacy_dismissed_proc_shells_file() -> Path:
    """Return the legacy dismissed-proc-shell JSON path."""
    return _DISMISSED_PROC_SHELLS_FILE or sase_home() / "dismissed_proc_shells.json"


def _read_ids_from_path(path: Path) -> set[str] | None:
    """Return ids from *path*, or ``None`` when the file is absent/unreadable."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    return _proc_ids_from_payload(data)


def load_dismissed_procs() -> set[str]:
    """Load dismissed proc ids from disk.

    Missing files, unreadable files, and malformed JSON yield an empty set.
    Non-string entries are ignored. Both the canonical object form
    ``{"schema_version": 1, "proc_ids": [...]}`` and a bare ``[...]`` list are
    accepted. Reads the new file, falling back to the legacy file when no new
    file exists.
    """
    ids = _read_ids_from_path(_dismissed_procs_file())
    if ids is not None:
        return ids
    # legacy sase-shell spelling: pre-rename hosts carry only the old file.
    legacy = _read_ids_from_path(_legacy_dismissed_proc_shells_file())
    return legacy if legacy is not None else set()


def record_dismissed_procs(
    proc_ids: Collection[str],
    *,
    live_proc_ids: Collection[str] | None = None,
) -> bool:
    """Union *proc_ids* into the persisted set and write atomically.

    When *live_proc_ids* is supplied, ids absent from that set are dropped.
    Read-modify-write so concurrent ACE instances cannot clobber each other's
    dismissals by writing a whole in-memory snapshot. Returns ``False`` on
    write failure rather than raising. Removes the legacy file only after a
    successful new-file write.
    """
    incoming = {item for item in proc_ids if isinstance(item, str) and item}
    with _LOCK:
        current = load_dismissed_procs()
        current.update(incoming)
        if live_proc_ids is not None:
            current.intersection_update(live_proc_ids)
        ok = _write_proc_ids(current)
        if ok:
            try:
                _legacy_dismissed_proc_shells_file().unlink(missing_ok=True)
            except OSError:
                pass
        return ok


def prune_dismissed_procs(live_proc_ids: Collection[str]) -> set[str]:
    """Drop persisted ids that are no longer in the durable proc store.

    Writes only when the set shrinks. Returns the pruned set even when the
    write is skipped or fails.
    """
    live = set(live_proc_ids)
    with _LOCK:
        current = load_dismissed_procs()
        pruned = current & live
        if pruned != current:
            _write_proc_ids(pruned)
        return pruned


def load_dismissed_proc_shells() -> set[str]:
    """Deprecated alias for :func:`load_dismissed_procs`."""

    return load_dismissed_procs()


def record_dismissed_proc_shells(
    proc_ids: Collection[str],
    *,
    live_proc_ids: Collection[str] | None = None,
) -> bool:
    """Deprecated alias for :func:`record_dismissed_procs`."""

    return record_dismissed_procs(proc_ids, live_proc_ids=live_proc_ids)


def prune_dismissed_proc_shells(live_proc_ids: Collection[str]) -> set[str]:
    """Deprecated alias for :func:`prune_dismissed_procs`."""

    return prune_dismissed_procs(live_proc_ids)


def _proc_ids_from_payload(data: object) -> set[str]:
    if isinstance(data, dict):
        raw_ids = data.get("proc_ids", [])
    elif isinstance(data, list):
        raw_ids = data
    else:
        return set()
    if not isinstance(raw_ids, list):
        return set()
    return {item for item in raw_ids if isinstance(item, str) and item}


def _write_proc_ids(proc_ids: set[str]) -> bool:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "proc_ids": sorted(proc_ids),
    }
    try:
        write_json_file_atomic(_dismissed_procs_file(), payload)
    except OSError:
        return False
    return True


__all__ = [
    "SCHEMA_VERSION",
    "load_dismissed_proc_shells",
    "load_dismissed_procs",
    "prune_dismissed_proc_shells",
    "prune_dismissed_procs",
    "record_dismissed_proc_shells",
    "record_dismissed_procs",
]
