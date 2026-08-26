"""Disabled-region-aware top-level ``---`` segment splitting for prompts.

``---`` on its own line is the multi-prompt segment separator, but a prompt
can also contain a ``%xprompts_enabled:false`` ... ``%xprompts_enabled:true``
disabled region (e.g. injected fork history) whose body carries ``---`` lines
as inert content, not segment boundaries. This module protects both fenced
code and disabled regions before splitting, so callers never mistake an
inert ``---`` for a real one.
"""

import re

from ._disabled_regions import protect_disabled_regions, unprotect_disabled_regions
from ._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks

_SEGMENT_SEPARATOR_RE = re.compile(r"^---\s*$", re.MULTILINE)


def split_prompt_segments(text: str) -> tuple[list[str], list[str]]:
    """Split *text* into top-level segments and the separators between them.

    Fenced blocks are protected before disabled regions (so a marker quoted
    inside a code fence stays inert), and each piece is restored in the
    reverse order (disabled regions first, then fenced blocks, so a fence
    nested inside a region is restored correctly) before being returned.
    Splitting itself happens on the fully protected text, so ``---`` lines
    inside a disabled region never produce a spurious segment.
    """
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(text, fenced_blocks)
    disabled_regions: list[str] = []
    protected = protect_disabled_regions(protected, disabled_regions)

    pieces = _SEGMENT_SEPARATOR_RE.split(protected)
    separators = _SEGMENT_SEPARATOR_RE.findall(protected)

    restored_pieces = [
        unprotect_fenced_blocks(
            unprotect_disabled_regions(piece, disabled_regions), fenced_blocks
        )
        for piece in pieces
    ]
    return restored_pieces, separators


__all__ = ["split_prompt_segments"]
