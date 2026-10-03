"""Shared note-status helpers for Memory panel rendering.

This module is private; the names it defines are public so the
``memory_panel_rendering_*`` sibling modules can share them without
importing ``_``-prefixed names across modules.
"""

from __future__ import annotations

from sase.memory.notes import MemoryNote


def note_is_invalid(note: MemoryNote) -> bool:
    """Return True when *note* has an invalid type or parent source."""
    return note.type_source == "invalid" or note.parent_source == "invalid"


__all__ = ["note_is_invalid"]
