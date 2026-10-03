"""Shared rail-glance types (phase rail-glance).

This module is private; the names it defines are public so the
``memory_pane_rail_glance_*`` sibling modules can share them without
importing ``_``-prefixed names across modules.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeletedSubject:
    """One subject whose latest feed entry is a deletion."""

    subject_id: str
    path: str
    display: str
    committer_time: int
    ordinal: int
    commit: str


__all__ = ["DeletedSubject"]
