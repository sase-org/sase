"""Shared types and timestamp helper for bead-touch panels.

Holds the pieces needed by both the touch loader and the merge view:
the display-event wrapper and the RFC 3339 moment parser. Names stay
public so the sibling private modules never import a ``_``-prefixed
name from each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sase.core.bead_touch_index_facade import BeadTouch


@dataclass(frozen=True)
class BeadTouchDisplayEvent:
    """One indexed touch paired with an optional session role label.

    ``agent_label`` is ``None`` for ordinary (single-member) rows so the
    existing per-agent shape is preserved; session rows set it to the
    producing member's compact role label (e.g. ``plan``, ``coder``).
    """

    touch: BeadTouch
    agent_label: str | None = None


def parse_moment(value: str | None) -> datetime | None:
    """Parse an RFC 3339 timestamp, or return ``None`` when unusable."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
