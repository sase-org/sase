"""Timing helpers for editable-install dev updates."""

from __future__ import annotations

from typing import Any


def slowest_reconcile_command(commands: tuple[Any, ...]) -> Any | None:
    """Return the slowest non-git command recorded for a dev update."""
    candidates = tuple(
        command
        for command in commands
        if not str(getattr(command, "label", "")).startswith("git ")
    )
    if not candidates:
        return None
    return max(candidates, key=lambda command: float(command.duration_seconds or 0.0))
