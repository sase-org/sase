"""Resolved SDD paths used by ACE event-refresh watchers."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_current_sdd_beads_dir() -> Path:
    """Resolve the effective beads directory for the current workspace."""
    from sase.sdd.store import resolve_sdd_kind_dir

    return resolve_sdd_kind_dir(Path.cwd(), 1, "beads")


def cached_sdd_beads_dir(owner: Any) -> Path:
    """Return the startup-cached SDD beads dir, falling back to the legacy path."""
    value = getattr(owner, "_sdd_beads_dir", None)
    if isinstance(value, Path):
        return value
    return Path.cwd() / "sdd" / "beads"
