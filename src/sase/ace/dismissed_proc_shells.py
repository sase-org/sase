"""Persistent tracking of dismissed stand-alone proc-shell Agents-tab rows.

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

_DISMISSED_PROC_SHELLS_FILE: Path | None = None
_LOCK = threading.Lock()


def _dismissed_proc_shells_file() -> Path:
    """Return the dismissed-proc-shell JSON path, honoring the test hook."""
    return _DISMISSED_PROC_SHELLS_FILE or sase_home() / "dismissed_proc_shells.json"


def load_dismissed_proc_shells() -> set[str]:
    """Load dismissed proc ids from disk.

    Missing files, unreadable files, and malformed JSON yield an empty set.
    Non-string entries are ignored. Both the canonical object form
    ``{"schema_version": 1, "proc_ids": [...]}`` and a bare ``[...]`` list are
    accepted.
    """
    path = _dismissed_proc_shells_file()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    return _proc_ids_from_payload(data)


def record_dismissed_proc_shells(
    proc_ids: Collection[str],
    *,
    live_proc_ids: Collection[str] | None = None,
) -> bool:
    """Union *proc_ids* into the persisted set and write atomically.

    When *live_proc_ids* is supplied, ids absent from that set are dropped.
    Read-modify-write so concurrent ACE instances cannot clobber each other's
    dismissals by writing a whole in-memory snapshot. Returns ``False`` on
    write failure rather than raising.
    """
    incoming = {item for item in proc_ids if isinstance(item, str) and item}
    with _LOCK:
        current = load_dismissed_proc_shells()
        current.update(incoming)
        if live_proc_ids is not None:
            current.intersection_update(live_proc_ids)
        return _write_proc_ids(current)


def prune_dismissed_proc_shells(live_proc_ids: Collection[str]) -> set[str]:
    """Drop persisted ids that are no longer in the durable proc store.

    Writes only when the set shrinks. Returns the pruned set even when the
    write is skipped or fails.
    """
    live = set(live_proc_ids)
    with _LOCK:
        current = load_dismissed_proc_shells()
        pruned = current & live
        if pruned != current:
            _write_proc_ids(pruned)
        return pruned


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
        write_json_file_atomic(_dismissed_proc_shells_file(), payload)
    except OSError:
        return False
    return True


__all__ = [
    "SCHEMA_VERSION",
    "load_dismissed_proc_shells",
    "prune_dismissed_proc_shells",
    "record_dismissed_proc_shells",
]
