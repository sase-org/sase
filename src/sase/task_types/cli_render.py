"""Shared Rich helpers for ``sase bead task-type``."""

from __future__ import annotations

from rich.console import Console

from ._models import TaskTypeRecord


def resolve_console(console: Console | None) -> Console:
    """Return the caller's console, or a plain one for real CLI runs."""

    if console is not None:
        return console
    return Console(highlight=False)


def record_accent(record: TaskTypeRecord) -> str:
    """Return the resolved accent hex, or a dim fallback."""

    return record.resolved_accent_color or "dim"


def record_glyph(record: TaskTypeRecord) -> str:
    """Return the resolved glyph, or a bullet if none was assigned."""

    return record.resolved_glyph or "•"


def yes_no(value: bool) -> str:
    """Spell a boolean the way the catalog table does."""

    return "yes" if value else "no"


__all__ = [
    "record_accent",
    "record_glyph",
    "resolve_console",
    "yes_no",
]
