"""Helpers for classifying macro content with prompt segment separators."""

from __future__ import annotations

import re

from sase.macro._fenced_blocks import protect_fenced_blocks
from sase.macro.models import Macro

_SEGMENT_SEPARATOR_RE = re.compile(r"^---\s*$", re.MULTILINE)


def macro_has_segment_separators(xp: Macro) -> bool:
    """Return True iff *xp*'s body contains a ``---`` line outside fenced blocks."""
    return macro_segment_count(xp) > 1


def macro_segment_count(xp: Macro) -> int:
    """Return the number of top-level prompt segments in *xp*."""
    blocks: list[str] = []
    protected = protect_fenced_blocks(xp.content, blocks)
    return len(_SEGMENT_SEPARATOR_RE.findall(protected)) + 1


__all__ = [
    "macro_has_segment_separators",
    "macro_segment_count",
]
