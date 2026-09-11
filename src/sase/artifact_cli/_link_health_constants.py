"""Shared markers and constants for artifact link health checks."""

from __future__ import annotations

LINKS_START = "<!-- sase:links:start -->"
LINKS_END = "<!-- sase:links:end -->"
REFERENCED_BY_START = "<!-- sase:referenced-by:start -->"
REFERENCED_BY_END = "<!-- sase:referenced-by:end -->"
RESOLVED_STATUSES = frozenset({"exact", "drifted", "vcs_backed"})

__all__ = [
    "LINKS_END",
    "LINKS_START",
    "REFERENCED_BY_END",
    "REFERENCED_BY_START",
    "RESOLVED_STATUSES",
]
