"""Persist the last `,<space>` agent selection across TUI restarts."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .tui.modals import SelectionItem

_LAST_SELECTION_FILE = Path.home() / ".sase" / "last_agent_selection.json"


def load_last_agent_selection() -> SelectionItem | None:
    """Load the last agent selection from disk.

    Returns:
        The persisted ``SelectionItem``, or ``None`` if the file is missing
        or contains invalid data.
    """
    if not _LAST_SELECTION_FILE.exists():
        return None

    try:
        with open(_LAST_SELECTION_FILE) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if (
            "display_name" not in data
            or "item_type" not in data
            or "project_name" not in data
        ):
            return None
        return SelectionItem(
            display_name=data["display_name"],
            item_type=data["item_type"],
            project_name=data["project_name"],
            cl_name=data.get("cl_name"),
        )
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        return None


def save_last_agent_selection(selection: SelectionItem) -> bool:
    """Save the last agent selection to disk.

    Args:
        selection: The selection to persist.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        _LAST_SELECTION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_LAST_SELECTION_FILE, "w") as f:
            json.dump(dataclasses.asdict(selection), f, indent=2)
        return True
    except OSError:
        return False
