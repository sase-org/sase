"""Working-context resolution for the Command Line panel.

The panel always shows where a command will run: the TUI's current project
resolved to its primary checkout, falling back to the TUI launch cwd. ``cd``
pins a directory (``cd -`` unpins); the chip marks a pinned context.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.cells import cell_len


@dataclass(frozen=True)
class CommandLineContext:
    """Where the next Command Line submission will run."""

    cwd: str
    project: str | None
    pinned: bool = False


def resolve_launch_cwd(app: Any) -> str:
    """Return the TUI launch working directory, defaulting to the process cwd."""
    for attr in ("_launch_cwd", "_tui_cwd", "launch_cwd"):
        value = getattr(app, attr, None)
        if isinstance(value, str) and value:
            return value
    try:
        return os.getcwd()
    except OSError:
        return ""


def resolve_working_context(
    app: Any,
    session: Any,
    *,
    launch_cwd: str | None = None,
) -> CommandLineContext:
    """Resolve the panel's working context (off-thread and cached by callers).

    A ``cd`` pin wins; otherwise the current project resolves to its primary
    checkout, falling back to the TUI launch cwd.
    """
    pin = getattr(session, "cwd_pin", None)
    if isinstance(pin, str) and pin:
        return CommandLineContext(cwd=pin, project=None, pinned=True)
    project: str | None = None
    cwd = launch_cwd if launch_cwd else resolve_launch_cwd(app)
    try:
        from sase.current_project import resolve_current_project

        resolved = resolve_current_project()
    except Exception:  # noqa: BLE001 - context display always degrades.
        resolved = None
    if resolved is not None:
        key = getattr(resolved, "key", None) or getattr(resolved, "name", None)
        if isinstance(key, str) and key:
            project = key
        checkout = _primary_checkout(resolved)
        if checkout:
            cwd = checkout
    return CommandLineContext(cwd=cwd, project=project, pinned=False)


def _primary_checkout(resolved: Any) -> str | None:
    for attr in ("primary_checkout", "checkout", "path", "root"):
        value = getattr(resolved, attr, None)
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, str) and value:
            return value
    if isinstance(resolved, dict):
        for key in ("primary_checkout", "checkout", "path", "root"):
            value = resolved.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def abbreviate_path(path: str) -> str:
    """Abbreviate a path with ``~`` for display in the context chip."""
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def middle_truncate(text: str, max_width: int) -> str:
    """Shorten *text* to at most *max_width* cells, eliding its middle with ``…``."""
    if max_width <= 0:
        return ""
    if cell_len(text) <= max_width:
        return text
    if max_width == 1:
        return "…"
    keep = max_width - 1
    head = keep // 2
    tail = keep - head
    return text[:head] + "…" + (text[len(text) - tail :] if tail else "")


def working_context_chip(
    context: CommandLineContext, *, max_width: int | None = 48
) -> str:
    """Render the context chip: ``⌂ +<project> · <path>`` (or just the path).

    ``max_width=None`` skips truncation so the border chrome can fit the chip
    to the live frame width itself.
    """
    path = abbreviate_path(context.cwd)
    if context.project:
        text = f"⌂ +{context.project} · {path}"
    else:
        text = f"⌂ {path}"
    if context.pinned:
        text += " (pinned)"
    if max_width is None:
        return text
    return middle_truncate(text, max_width)


__all__ = [
    "CommandLineContext",
    "abbreviate_path",
    "middle_truncate",
    "resolve_launch_cwd",
    "resolve_working_context",
    "working_context_chip",
]
