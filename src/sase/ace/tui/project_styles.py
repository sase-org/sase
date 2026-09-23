"""Deterministic, collision-free accent colors for enabled projects.

Backed by :mod:`sase.project_accents` (the D6 shared backend); this module
keeps re-exports so existing TUI importers keep working.
"""

from __future__ import annotations

from sase.palette_hash import hash_palette_index as _hash_index
from sase.project_accents import (
    PROJECT_ACCENTS as PROJECT_ACCENTS,
    accent_among_keys as accent_among_keys,
    project_accent as project_accent,
    project_accent_index as project_accent_index,
)

__all__ = [
    "PROJECT_ACCENTS",
    "_hash_index",
    "accent_among_keys",
    "project_accent",
    "project_accent_index",
]
