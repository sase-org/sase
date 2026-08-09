"""Persistent mapping from query string to selected Patch name."""

import json
from pathlib import Path

from sase.core.paths import sase_home

MAX_SELECTIONS = 200
_QUERY_SELECTION_FILE: Path | None = None


def _query_selection_file() -> Path:
    return _QUERY_SELECTION_FILE or sase_home() / "query_selections.json"


def load_query_selections() -> dict[str, str]:
    """Load query-to-selection mapping from disk.

    Returns:
        Dict mapping canonical query strings to Patch names.
    """
    path = _query_selection_file()
    if not path.exists():
        return {}

    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def save_query_selections(selections: dict[str, str]) -> bool:
    """Save query-to-selection mapping to disk, trimming oldest entries.

    Uses pop+re-insert to keep recently-used entries at the end so
    trimming discards the least-recently-used entries.

    Args:
        selections: Dict mapping canonical query strings to Patch names.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        path = _query_selection_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Trim oldest entries if over limit (keep most recent at end)
        if len(selections) > MAX_SELECTIONS:
            keys = list(selections.keys())
            for key in keys[: len(keys) - MAX_SELECTIONS]:
                del selections[key]
        with open(path, "w") as f:
            json.dump(selections, f, indent=2)
        return True
    except OSError:
        return False
