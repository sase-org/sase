"""Shared constants for the new-project create stage.

This module is private; the names it defines are public so the
``new_project_create_*`` sibling modules can share them without
importing ``_``-prefixed names across modules.
"""

from __future__ import annotations

BARE_GIT_WORKFLOW = "git"

__all__ = ["BARE_GIT_WORKFLOW"]
