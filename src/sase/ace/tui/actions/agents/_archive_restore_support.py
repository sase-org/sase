"""Archive-restore shared helpers.

Support seam for the Archive restore split. ``notify_owner`` and
``archive_light_name`` are deliberately public names inside this
already-private module so the split restore modules can share them without
importing a ``_``-prefixed name across modules. The public import path stays
:mod:`sase.ace.tui.actions.agents._archive_restore`, which does not
re-export these helpers.
"""

from __future__ import annotations

from typing import Any


def notify_owner(owner: Any, message: str, *, severity: str = "information") -> None:
    """Toast ``message`` on ``owner`` when it supports ``notify``."""
    notify = getattr(owner, "notify", None)
    if callable(notify):
        try:
            notify(message, severity=severity)
        except Exception:
            pass


def archive_light_name(light_row: Any) -> str:
    """Return the display name for an Archive light row."""
    if light_row is None:
        return "archived run"
    try:
        return str(
            light_row.get("agent_name") or light_row.get("name") or "archived run"
        )
    except Exception:
        return "archived run"


__all__ = [
    "archive_light_name",
    "notify_owner",
]
