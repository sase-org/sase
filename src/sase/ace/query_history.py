"""Pane-namespaced storage for query history stacks (prev/next navigation).

See :mod:`sase.ace.saved_queries` for the shared legacy-migration shape and
rationale: a legacy ``{"prev": [...], "next": [...]}`` file predates pane
namespacing and was always implicitly the Patches pane's data, so it is
read-time migrated by lifting it under the ``"patches"`` key. The legacy
bytes are never modified or deleted; the migrated shape is written back
(write-then-read validated) only on success.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

from ._query_persistence_io import write_json_validated
from .query_record import QueryRecord

# Stack configuration
MAX_STACK_SIZE = 50
_QUERY_HISTORY_FILE: Path | None = None
_LEGACY_KEYS = frozenset({"prev", "next"})


def _query_history_file() -> Path:
    return _QUERY_HISTORY_FILE or sase_home() / "query_history.json"


@dataclass
class QueryHistoryStacks:
    """Data class holding prev and next stacks for one pane."""

    prev: list[QueryRecord]  # Most recent at end (append/pop from end)
    next: list[QueryRecord]  # Most recent at end (append/pop from end)


def _read_raw() -> dict[str, Any]:
    path = _query_history_file()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _records_from_wire(raw: Any) -> list[QueryRecord]:
    if not isinstance(raw, list):
        return []
    records = (QueryRecord.from_wire(item) for item in raw[-MAX_STACK_SIZE:])
    return [record for record in records if record is not None]


def _load_all_panes() -> dict[str, QueryHistoryStacks]:
    data = _read_raw()
    if set(data.keys()) <= _LEGACY_KEYS:
        migrated = {
            "patches": QueryHistoryStacks(
                prev=_records_from_wire(data.get("prev", [])),
                next=_records_from_wire(data.get("next", [])),
            )
        }
        _write_all_panes(migrated)
        return migrated

    panes: dict[str, QueryHistoryStacks] = {}
    for pane_id, stacks in data.items():
        if not isinstance(pane_id, str) or not isinstance(stacks, dict):
            continue
        panes[pane_id] = QueryHistoryStacks(
            prev=_records_from_wire(stacks.get("prev", [])),
            next=_records_from_wire(stacks.get("next", [])),
        )
    return panes


def _write_all_panes(panes: dict[str, QueryHistoryStacks]) -> bool:
    payload = {
        pane_id: {
            "prev": [r.to_wire() for r in stacks.prev[-MAX_STACK_SIZE:]],
            "next": [r.to_wire() for r in stacks.next[-MAX_STACK_SIZE:]],
        }
        for pane_id, stacks in panes.items()
    }
    return write_json_validated(_query_history_file(), payload)


def copy_query_history_stacks(stacks: QueryHistoryStacks) -> QueryHistoryStacks:
    """Return a detached copy of one pane's history stacks."""
    return QueryHistoryStacks(prev=list(stacks.prev), next=list(stacks.next))


def snapshot_query_history(
    panes: dict[str, QueryHistoryStacks],
) -> dict[str, QueryHistoryStacks]:
    """Return a detached, max-bounded copy of every pane history bucket."""
    return {
        pane_id: QueryHistoryStacks(
            prev=list(stacks.prev[-MAX_STACK_SIZE:]),
            next=list(stacks.next[-MAX_STACK_SIZE:]),
        )
        for pane_id, stacks in panes.items()
    }


def load_all_query_history() -> dict[str, QueryHistoryStacks]:
    """Load every pane's query-history stacks from disk."""
    return snapshot_query_history(_load_all_panes())


def save_all_query_history(panes: dict[str, QueryHistoryStacks]) -> bool:
    """Persist a detached map of all pane history stacks."""
    return _write_all_panes(snapshot_query_history(panes))


def load_query_history(pane_id: str) -> QueryHistoryStacks:
    """Load query history stacks for *pane_id* from disk.

    Returns:
        QueryHistoryStacks with prev and next lists.
    """
    return _load_all_panes().get(pane_id) or QueryHistoryStacks(prev=[], next=[])


def save_query_history(pane_id: str, stacks: QueryHistoryStacks) -> bool:
    """Save query history stacks for *pane_id* to disk.

    Args:
        pane_id: The owning Artifacts pane id.
        stacks: The QueryHistoryStacks to save.

    Returns:
        True if saved successfully, False otherwise.
    """
    panes = _load_all_panes()
    panes[pane_id] = copy_query_history_stacks(stacks)
    return save_all_query_history(panes)


def _remove_and_append(stack: list[QueryRecord], record: QueryRecord) -> None:
    """Remove any entry sharing *record*'s canonical form, then append."""
    for index, existing in enumerate(stack):
        if existing.canonical == record.canonical:
            del stack[index]
            break
    stack.append(record)


def push_to_prev_stack(current: QueryRecord, stacks: QueryHistoryStacks) -> None:
    """Push current query to prev stack and clear next stack.

    This is called when user manually changes the query (via / or saved query).

    Args:
        current: The query being replaced (to push to prev).
        stacks: The stacks to modify (in-place).
    """
    _remove_and_append(stacks.prev, current)
    # Enforce max size
    if len(stacks.prev) > MAX_STACK_SIZE:
        stacks.prev = stacks.prev[-MAX_STACK_SIZE:]
    # Clear next stack on new navigation
    stacks.next.clear()


def navigate_prev(
    current: QueryRecord, stacks: QueryHistoryStacks
) -> QueryRecord | None:
    """Navigate to previous query.

    Args:
        current: The current query (to push to next).
        stacks: The stacks to modify (in-place).

    Returns:
        The previous query record, or None if prev stack is empty.
    """
    if not stacks.prev:
        return None

    # Push current to next stack (removing old duplicate if any)
    _remove_and_append(stacks.next, current)

    # Pop from prev stack
    return stacks.prev.pop()


def navigate_next(
    current: QueryRecord, stacks: QueryHistoryStacks
) -> QueryRecord | None:
    """Navigate to next query.

    Args:
        current: The current query (to push to prev).
        stacks: The stacks to modify (in-place).

    Returns:
        The next query record, or None if next stack is empty.
    """
    if not stacks.next:
        return None

    # Push current to prev stack (removing old duplicate if any)
    _remove_and_append(stacks.prev, current)

    # Pop from next stack
    return stacks.next.pop()


__all__ = [
    "MAX_STACK_SIZE",
    "QueryHistoryStacks",
    "copy_query_history_stacks",
    "load_all_query_history",
    "load_query_history",
    "navigate_next",
    "navigate_prev",
    "push_to_prev_stack",
    "save_all_query_history",
    "save_query_history",
    "snapshot_query_history",
]
