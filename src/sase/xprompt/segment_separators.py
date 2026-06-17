"""Helpers for classifying xprompt content with prompt segment separators."""

from __future__ import annotations

import re

from sase.xprompt._fenced_blocks import protect_fenced_blocks
from sase.xprompt.models import XPrompt

_SEGMENT_SEPARATOR_RE = re.compile(r"^---\s*$", re.MULTILINE)


def xprompt_has_segment_separators(xp: XPrompt) -> bool:
    """Return True iff *xp*'s body contains a ``---`` line outside fenced blocks."""
    blocks: list[str] = []
    protected = protect_fenced_blocks(xp.content, blocks)
    return bool(_SEGMENT_SEPARATOR_RE.search(protected))


__all__ = [
    "xprompt_has_segment_separators",
]
