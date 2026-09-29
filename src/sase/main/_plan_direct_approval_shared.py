"""Shared helpers needed by more than one direct-approval module.

Public names only: sibling ``plan_direct_approval_*`` modules import these
without touching a ``_``-prefixed symbol.
"""

from __future__ import annotations

from pathlib import Path


def plan_stem(source_path: Path) -> str:
    """Return the plan name without extension or ``sase_plan_`` prefix."""
    name = source_path.stem
    if name.startswith("sase_plan_"):
        name = name[len("sase_plan_") :]
    return name


__all__ = ["plan_stem"]
