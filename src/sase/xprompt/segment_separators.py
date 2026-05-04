"""Helpers for classifying xprompt content with prompt segment separators."""

from __future__ import annotations

import re

from sase.xprompt._fenced_blocks import protect_fenced_blocks
from sase.xprompt.models import XPrompt

_SEGMENT_SEPARATOR_RE = re.compile(r"^---\s*$", re.MULTILINE)


def xprompt_content_has_segment_separators(content: str) -> bool:
    """Return True iff *content* contains a ``---`` line outside fenced blocks."""
    blocks: list[str] = []
    protected = protect_fenced_blocks(content, blocks)
    return bool(_SEGMENT_SEPARATOR_RE.search(protected))


def xprompt_has_segment_separators(xp: XPrompt) -> bool:
    """Return True iff *xp*'s body contains a ``---`` line outside fenced blocks."""
    return xprompt_content_has_segment_separators(xp.content)


__all__ = [
    "xprompt_content_has_segment_separators",
    "xprompt_has_segment_separators",
]
