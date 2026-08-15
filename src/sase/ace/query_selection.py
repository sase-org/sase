"""Pane-namespaced persistent mapping from query string to selected entry.

Each pane's map is canonical query string -> the selected row's
:class:`~sase.ace.tui.widgets.artifacts.entry_navigation.ArtifactEntryTarget`
token (``ArtifactEntryTarget.to_token()``), not a bare display name, so a
restore is unambiguous even across rows that share a display name in
different projects.

See :mod:`sase.ace.saved_queries` for the shared legacy-migration shape and
rationale: a legacy ``{"canonical": "name", ...}`` file predates pane
namespacing and was always implicitly the Patches pane's data, so it is
read-time migrated by lifting it under the ``"patches"`` key. The legacy
bytes are never modified or deleted; the migrated shape is written back
(write-then-read validated) only on success.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

from ._query_persistence_io import write_json_validated

MAX_SELECTIONS = 200
_QUERY_SELECTION_FILE: Path | None = None


def _query_selection_file() -> Path:
    return _QUERY_SELECTION_FILE or sase_home() / "query_selections.json"


def _read_raw() -> dict[str, Any]:
    path = _query_selection_file()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _is_legacy_shape(data: dict[str, Any]) -> bool:
    """Legacy files map query -> bare selection string, not pane -> map."""
    return bool(data) and all(isinstance(v, str) for v in data.values())


def _load_all_panes() -> dict[str, dict[str, str]]:
    data = _read_raw()
    if _is_legacy_shape(data):
        migrated = {"patches": dict(data)}
        _write_all_panes(migrated)
        return migrated

    panes: dict[str, dict[str, str]] = {}
    for pane_id, selections in data.items():
        if not isinstance(pane_id, str) or not isinstance(selections, dict):
            continue
        panes[pane_id] = {
            key: value
            for key, value in selections.items()
            if isinstance(key, str) and isinstance(value, str)
        }
    return panes


def _write_all_panes(panes: dict[str, dict[str, str]]) -> bool:
    return write_json_validated(_query_selection_file(), panes)


def load_query_selections(pane_id: str) -> dict[str, str]:
    """Load query-to-selection mapping for *pane_id* from disk.

    Returns:
        Dict mapping canonical query strings to ``ArtifactEntryTarget``
        tokens.
    """
    return _load_all_panes().get(pane_id, {})


def save_query_selections(pane_id: str, selections: dict[str, str]) -> bool:
    """Save query-to-selection mapping for *pane_id* to disk, trimming oldest.

    Uses pop+re-insert to keep recently-used entries at the end so
    trimming discards the least-recently-used entries.

    Args:
        pane_id: The owning Artifacts pane id.
        selections: Dict mapping canonical query strings to
            ``ArtifactEntryTarget`` tokens.

    Returns:
        True if saved successfully, False otherwise.
    """
    trimmed = dict(selections)
    if len(trimmed) > MAX_SELECTIONS:
        keys = list(trimmed.keys())
        for key in keys[: len(keys) - MAX_SELECTIONS]:
            del trimmed[key]
    panes = _load_all_panes()
    panes[pane_id] = trimmed
    return _write_all_panes(panes)


__all__ = [
    "MAX_SELECTIONS",
    "load_query_selections",
    "save_query_selections",
]
