"""Shared Changes-lens constants for the ``C`` changeset review.

This module is private; the names it defines are public so the
``memory_pane_changes_*`` sibling modules can share them without
importing ``_``-prefixed names across modules.
"""

from __future__ import annotations

#: Rail row id prefix for lens rows (never collides with note identities,
#: which are repo-relative paths or ``web:strand`` selectors).
CHANGES_ROW_PREFIX = "changes:"

#: Trailing rail row id for the window-extension line.
MORE_ROW_ID = f"{CHANGES_ROW_PREFIX}more"


__all__ = ["CHANGES_ROW_PREFIX", "MORE_ROW_ID"]
