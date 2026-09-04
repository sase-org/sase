"""Precompute unified diffs for an init-check payload off the event loop.

TUI perf rule 1 forbids disk I/O in render paths, and the epic requires full
unified diffs with no second pass. Build every diff on the check worker thread
and hand the modal pure text.
"""

from __future__ import annotations

import difflib
from dataclasses import replace
from pathlib import Path

from .projects_pane_init_payload import InitActionRow, InitCheckPayload, InitPlannerRow

MAX_DIFF_LINES = 400
_BINARY_NOTE = "binary content"
_NO_CONTENT_NOTE = "no file content in this plan"
_UNAVAILABLE_NOTE = "diff unavailable"


def attach_action_diffs(payload: InitCheckPayload) -> InitCheckPayload:
    """Rebuild *payload* with ``diff_lines`` / diffstat filled in per action."""
    projects = tuple(
        replace(
            project,
            planners=tuple(_diff_planner(planner) for planner in project.planners),
        )
        for project in payload.projects
    )
    return replace(payload, projects=projects)


def _diff_planner(planner: InitPlannerRow) -> InitPlannerRow:
    return replace(
        planner,
        actions=tuple(_diff_action(action) for action in planner.actions),
    )


def _diff_action(action: InitActionRow) -> InitActionRow:
    if action.new_content_encoding == "base64":
        return replace(
            action, diff_note=_BINARY_NOTE, diff_lines=(), added=0, removed=0
        )
    if action.operation == "delete":
        old_text, note = _read_old_text(action.path, operation="delete")
        return _unified(action, old_text, "", note)
    if action.new_content is None:
        return replace(
            action,
            diff_note=_NO_CONTENT_NOTE,
            diff_lines=(),
            added=0,
            removed=0,
        )
    old_text, note = _read_old_text(action.path, operation=action.operation)
    return _unified(action, old_text, action.new_content, note)


def _read_old_text(path_text: str, *, operation: str) -> tuple[str, str | None]:
    path = Path(path_text)
    if operation == "create":
        if not path.is_absolute():
            return "", None
        if not path.is_file():
            return "", None
        try:
            return path.read_text(encoding="utf-8"), None
        except (OSError, UnicodeDecodeError):
            return "", None
    if not path.is_absolute() or not path.is_file():
        return "", _UNAVAILABLE_NOTE
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError):
        return "", _UNAVAILABLE_NOTE


def _unified(
    action: InitActionRow,
    old: str,
    new: str,
    note: str | None,
) -> InitActionRow:
    display = action.path or "file"
    lines = list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=display,
            tofile=display,
            lineterm="",
        )
    )
    added = sum(
        1 for line in lines if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in lines if line.startswith("-") and not line.startswith("---")
    )
    if len(lines) > MAX_DIFF_LINES:
        extra = len(lines) - MAX_DIFF_LINES
        lines = [*lines[:MAX_DIFF_LINES], f"… {extra} more diff lines"]
    return replace(
        action,
        added=added,
        removed=removed,
        diff_lines=tuple(lines),
        diff_note=note,
        new_content=None,
        new_content_encoding=None,
    )


__all__ = ["MAX_DIFF_LINES", "attach_action_diffs"]
