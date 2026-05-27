"""Persist the last `,<space>` agent selection across TUI restarts."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Literal, cast

from sase.core.paths import sase_home

from .tui.modals import SelectionItem

_LAST_SELECTION_FILE: Path | None = None
_SelectionItemType = Literal["project", "cl", "home", "all"]
_VALID_ITEM_TYPES: set[_SelectionItemType] = {"project", "cl", "home", "all"}


def _last_selection_file() -> Path:
    return _LAST_SELECTION_FILE or sase_home() / "last_agent_selection.json"


def load_last_agent_selection() -> SelectionItem | None:
    """Load the last agent selection from disk.

    Returns:
        The persisted ``SelectionItem``, or ``None`` if the file is missing
        or contains invalid data.
    """
    path = _last_selection_file()
    if not path.exists():
        return None

    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if (
            "display_name" not in data
            or "item_type" not in data
            or "project_name" not in data
        ):
            return None
        display_name = data["display_name"]
        item_type = data["item_type"]
        project_name = data["project_name"]
        cl_name = data.get("cl_name")
        if (
            not isinstance(display_name, str)
            or not isinstance(item_type, str)
            or item_type not in _VALID_ITEM_TYPES
            or not isinstance(project_name, str)
            or (cl_name is not None and not isinstance(cl_name, str))
        ):
            return None
        item_type = cast(_SelectionItemType, item_type)
        return SelectionItem(
            display_name=display_name,
            item_type=item_type,
            project_name=project_name,
            cl_name=cl_name,
        )
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        return None


def _save_last_agent_selection(selection: SelectionItem) -> bool:
    """Save the last agent selection to disk.

    Args:
        selection: The selection to persist.

    Returns:
        True if saved successfully, False otherwise.
    """
    try:
        path = _last_selection_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(dataclasses.asdict(selection), f, indent=2)
        return True
    except OSError:
        return False


def save_last_agent_selection_if_launchable(selection: SelectionItem) -> bool:
    """Persist *selection* only if its project is launchable.

    ``home`` and ``all`` selections are always persisted. ``project`` and
    ``cl`` selections are skipped when ``selection.project_name`` does not
    refer to a currently launchable project on disk; this prevents stale
    or bogus project names (e.g. an auto-created ``.gp`` for a non-cloned
    GitHub repo) from being saved as the next ``,<space>`` replay target.
    """
    if selection.item_type in ("home", "all"):
        return _save_last_agent_selection(selection)
    from sase.ace.tui.modals.project_discovery import is_launchable_project

    if not is_launchable_project(selection.project_name):
        return False
    return _save_last_agent_selection(selection)


def clear_last_agent_selection() -> bool:
    """Remove the persisted last agent selection, best-effort.

    Returns:
        True if the selection file was removed, False if it was absent or
        could not be removed.
    """
    try:
        _last_selection_file().unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
