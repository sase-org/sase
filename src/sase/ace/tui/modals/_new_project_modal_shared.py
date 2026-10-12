"""Shared constants for the New Project wizard shell split.

This module is private; the names it defines are public so the
``new_project_modal_*`` sibling modules can share them without
importing ``_``-prefixed names across modules.
"""

from __future__ import annotations

MODAL_TASKS = "_new_project_modal_tasks"

__all__ = ["MODAL_TASKS"]
