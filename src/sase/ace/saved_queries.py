"""Pane-namespaced storage for saved search-query slots.

``saved_queries.json`` holds one slot map per Artifacts pane id (see
:mod:`sase.ace.query_profile.profiles` for the pane id vocabulary). The
legacy shape -- a single flat ``{"1": "canonical", ...}`` map with no pane
namespacing -- predates this and was always implicitly the Patches pane's
data, so a legacy file is read-time migrated by lifting it under the
``"patches"`` key. The legacy bytes are never modified or deleted: the
migrated shape is written back (write-then-read validated) only on success,
and a failed write just means the same migration runs again next load.

``last_query.txt`` is unrelated to pane namespacing: it seeds the ``sase
ace`` CLI's default query on the next cold start, which is always the
Patches pane's boolean query, so it stays a single unnamespaced file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

from ._query_persistence_io import write_json_validated
from .query_record import QueryRecord, current_profile_digest

# Key order: 0 is first, 9 is last
KEY_ORDER = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]

# Cache file locations
_SAVED_QUERIES_FILE: Path | None = None
_LAST_QUERY_FILE: Path | None = None


def _saved_queries_file() -> Path:
    return _SAVED_QUERIES_FILE or sase_home() / "saved_queries.json"


def _last_query_file() -> Path:
    return _LAST_QUERY_FILE or sase_home() / "last_query.txt"


def _read_raw() -> dict[str, Any]:
    path = _saved_queries_file()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _is_legacy_shape(data: dict[str, Any]) -> bool:
    """Legacy files map slot -> bare canonical string, not slot -> record."""
    return bool(data) and all(isinstance(v, str) for v in data.values())


def _load_all_panes() -> dict[str, dict[str, QueryRecord]]:
    data = _read_raw()
    if _is_legacy_shape(data):
        migrated = {
            "patches": {
                slot: QueryRecord(source=value, canonical=value)
                for slot, value in data.items()
                if slot in KEY_ORDER and isinstance(value, str)
            }
        }
        _write_all_panes(migrated)
        return migrated

    panes: dict[str, dict[str, QueryRecord]] = {}
    for pane_id, slots in data.items():
        if not isinstance(pane_id, str) or not isinstance(slots, dict):
            continue
        pane_records: dict[str, QueryRecord] = {}
        for slot, raw in slots.items():
            if slot not in KEY_ORDER:
                continue
            record = QueryRecord.from_wire(raw)
            if record is not None:
                pane_records[slot] = record
        panes[pane_id] = pane_records
    return panes


def _write_all_panes(panes: dict[str, dict[str, QueryRecord]]) -> bool:
    payload = {
        pane_id: {slot: record.to_wire() for slot, record in slots.items()}
        for pane_id, slots in panes.items()
    }
    return write_json_validated(_saved_queries_file(), payload)


def load_saved_queries(pane_id: str) -> dict[str, QueryRecord]:
    """Load saved-query slots for *pane_id* ("0"-"9" -> record).

    Returns:
        Dictionary mapping slot number ("0"-"9") to its saved record.
    """
    return _load_all_panes().get(pane_id, {})


def find_slot_for_query(pane_id: str, canonical: str) -> str | None:
    """Find the slot containing a given canonical query on *pane_id*.

    Args:
        pane_id: The owning Artifacts pane id.
        canonical: The canonical query string to search for.

    Returns:
        The slot number string if found, or None if the query is not saved.
    """
    for slot, record in load_saved_queries(pane_id).items():
        if record.canonical == canonical:
            return slot
    return None


def save_query(pane_id: str, slot: str, source: str, canonical: str) -> bool:
    """Save a query to a specific slot on *pane_id*.

    If the query already exists in a different slot on this pane, it is
    removed from the old slot (i.e. the query is moved, not duplicated).

    Args:
        pane_id: The owning Artifacts pane id.
        slot: The slot number ("0"-"9")
        source: The query text as the user typed it.
        canonical: The canonical (normalized) form of *source*.

    Returns:
        True if saved successfully, False otherwise.
    """
    if slot not in KEY_ORDER:
        return False

    panes = _load_all_panes()
    slots = dict(panes.get(pane_id, {}))
    for old_slot, record in list(slots.items()):
        if record.canonical == canonical and old_slot != slot:
            del slots[old_slot]
    slots[slot] = QueryRecord(
        source=source,
        canonical=canonical,
        profile_digest=current_profile_digest(pane_id),
    )
    panes[pane_id] = slots
    return _write_all_panes(panes)


def delete_query(pane_id: str, slot: str) -> bool:
    """Delete a query from a specific slot on *pane_id*.

    Args:
        pane_id: The owning Artifacts pane id.
        slot: The slot number ("0"-"9")

    Returns:
        True if deleted (or slot was already empty), False on error.
    """
    panes = _load_all_panes()
    slots = dict(panes.get(pane_id, {}))
    if slot in slots:
        del slots[slot]
        panes[pane_id] = slots
        return _write_all_panes(panes)
    return True  # Slot was already empty


def get_next_available_slot(queries: dict[str, QueryRecord]) -> str | None:
    """Get the next available slot in order 1,2,3...9,0.

    Args:
        queries: Current saved queries dict for one pane.

    Returns:
        Slot number string, or None if all slots are full.
    """
    for slot in KEY_ORDER:
        if slot not in queries:
            return slot
    return None


def load_first_saved_query(pane_id: str) -> str | None:
    """Load the first saved query's source text on *pane_id*.

    Checks slots 1-9 then 0.

    Returns:
        The first saved query's source text, or None if none exist.
    """
    queries = load_saved_queries(pane_id)
    for slot in KEY_ORDER[1:] + KEY_ORDER[:1]:
        if slot in queries:
            return queries[slot].source
    return None


def load_last_query() -> str | None:
    """Load the last used Patches query from disk.

    Returns:
        The last used query string, or None if no saved query exists.
    """
    path = _last_query_file()
    if not path.exists():
        return None
    try:
        content = path.read_text().strip()
        return content or None
    except OSError:
        return None


def save_last_query(query: str) -> bool:
    """Save the current Patches query as the last used query.

    Args:
        query: The canonical query string to save.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        path = _last_query_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(query)
        return True
    except OSError:
        return False


__all__ = [
    "KEY_ORDER",
    "delete_query",
    "find_slot_for_query",
    "get_next_available_slot",
    "load_first_saved_query",
    "load_last_query",
    "load_saved_queries",
    "save_last_query",
    "save_query",
]
