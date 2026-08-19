"""Handlers for ``sase project current`` and ``sase project set-current``."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.text import Text

from sase.ace.tui.project_styles import project_accent
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.current_project import (
    CurrentProject,
    SetCurrentProjectOutcome,
    resolve_current_project,
    set_current_project,
)

_NO_CURRENT_PROJECT_MESSAGE = (
    "No current project.\n"
    "Launch an agent on a project, or run `sase project set-current`, "
    "to make it current."
)
_SET_CURRENT_SUCCESS = frozenset({"set", "unchanged"})


def _mru_ref_for(current: CurrentProject) -> str:
    if current.workflow_type:
        return f"#{current.workflow_type}:{current.origin_ref}"
    return current.origin_ref


def _current_json_payload(current: CurrentProject) -> dict[str, object]:
    return {
        "display_name": current.display_name,
        "mru_ref": _mru_ref_for(current),
        "origin": current.origin,
        "origin_ref": current.origin_ref,
        "project_key": current.project_key,
        "workflow_type": current.workflow_type,
    }


def _enabled_project_keys() -> list[str]:
    try:
        records = list_project_records(
            sase_projects_dir(),
            "enabled",
            include_home=False,
        )
    except (OSError, ValueError, ImportError, AttributeError):
        return []
    return [record.project_name for record in records if record.is_project]


def _origin_display(current: CurrentProject) -> str:
    if current.origin == "patch":
        return f"patch ({current.origin_ref})"
    return current.origin


def _accent_for(project_key: str) -> str:
    return project_accent(project_key, among=_enabled_project_keys())


def _print_current_human(
    current: CurrentProject,
    *,
    console: Console | None = None,
) -> None:
    output = console or Console()
    accent = _accent_for(current.project_key)
    title = Text()
    title.append("+", style=f"dim {accent}")
    title.append(current.display_name, style=f"bold {accent}")
    output.print(title)
    output.print(f"Directory key: {current.project_key}")
    output.print(f"Origin: {_origin_display(current)}")
    output.print(f"MRU ref: {_mru_ref_for(current)}")


def handle_current(args: argparse.Namespace) -> int:
    """Print the current project for ``sase project current``."""
    try:
        current = resolve_current_project()
    except (OSError, ValueError, ImportError, AttributeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        payload = None if current is None else _current_json_payload(current)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if current is None:
        print(_NO_CURRENT_PROJECT_MESSAGE)
        return 0

    _print_current_human(current)
    return 0


def _set_current_json_payload(
    outcome: SetCurrentProjectOutcome,
) -> dict[str, object]:
    return {
        "message": outcome.message,
        "project": (
            None if outcome.project is None else _current_json_payload(outcome.project)
        ),
        "status": outcome.status,
    }


def handle_set_current(args: argparse.Namespace) -> int:
    """Set the current project for ``sase project set-current``."""
    try:
        outcome: SetCurrentProjectOutcome = set_current_project(str(args.project))
    except (OSError, ValueError, ImportError, AttributeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    success = outcome.status in _SET_CURRENT_SUCCESS
    if args.json:
        print(json.dumps(_set_current_json_payload(outcome), indent=2, sort_keys=True))
        return 0 if success else 1

    if not success:
        print(outcome.message, file=sys.stderr)
        return 1

    print(outcome.message)
    if outcome.project is not None:
        _print_current_human(outcome.project)
    return 0
