"""Persist the last `,Ctrl+Space` agent selection across TUI restarts."""

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
        selection = SelectionItem(
            display_name=display_name,
            item_type=item_type,
            project_name=project_name,
            cl_name=cl_name,
        )
        return _normalize_selection(selection)
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
        selection = _normalize_selection(selection)
        path = _last_selection_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            # Preserve the existing wire shape. Identity fields are canonical;
            # the compatibility ``display_name`` is recomputed on load/replay.
            json.dump(
                {
                    "display_name": selection.display_name,
                    "item_type": selection.item_type,
                    "project_name": selection.project_name,
                    "cl_name": selection.cl_name,
                },
                f,
                indent=2,
            )
        return True
    except OSError:
        return False


def save_last_agent_selection_if_launchable(selection: SelectionItem) -> bool:
    """Persist *selection* only if its project is launchable.

    ``home`` and ``all`` selections are always persisted. ``project`` and
    ``cl`` selections are skipped when ``selection.project_name`` does not
    refer to a currently launchable project on disk; this prevents stale
    or bogus project names (e.g. an auto-created ``.gp`` for a non-cloned
    GitHub repo) from being saved as the next ``,Ctrl+Space`` replay target.
    """
    if selection.item_type in ("home", "all"):
        return _save_last_agent_selection(selection)
    from sase.ace.tui.modals.project_discovery import is_launchable_project

    normalized_selection = _normalize_selection(selection)
    if not is_launchable_project(normalized_selection.project_name):
        return False
    return _save_last_agent_selection(selection)


def _normalize_selection(selection: SelectionItem) -> SelectionItem:
    """Canonicalize persisted identity and refresh its presentation label."""
    if selection.item_type in ("home", "all"):
        return selection

    from sase.project_aliases import resolve_project_alias_ref
    from sase.project_display_names import (
        humanize_cl_name,
        load_project_display_snapshot,
    )

    project_name = resolve_project_alias_ref(selection.project_name)
    display_snapshot = load_project_display_snapshot()
    project_label = display_snapshot.label_for(project_name)
    if selection.item_type == "project":
        selection_label = project_label
        display_name = f"[P] {selection_label}"
    else:
        selection_label = humanize_cl_name(
            selection.cl_name or "",
            snapshot=display_snapshot,
        )
        display_name = f"[PR] {selection_label}"
    return dataclasses.replace(
        selection,
        display_name=display_name,
        project_name=project_name,
        project_label=project_label,
        selection_label=selection_label,
    )


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
