"""Fenced code block protection for xprompt processing.

Provides utilities to extract fenced code blocks (triple-backtick) from text
before xprompt expansion and restore them afterward, preventing content inside
code blocks from being treated as xprompt references.
"""

import re

_FENCED_CODE_BLOCK_RE = re.compile(r"(`{3,})[^\n]*\n[\s\S]*?\1")
_PLACEHOLDER_PREFIX = "\x00XPF_"
_PLACEHOLDER_SUFFIX = "\x00"


def protect_fenced_blocks(text: str, blocks: list[str]) -> str:
    """Replace fenced code blocks with null-byte placeholders.

    Each extracted block is appended to ``blocks``, using the list length
    as the starting index for placeholder numbering.  This allows the
    function to be called multiple times (e.g. once before the expansion
    loop and again after each iteration) without placeholder collisions.

    Args:
        text: The text to scan for fenced code blocks.
        blocks: Mutable list that accumulates extracted block content.

    Returns:
        The text with fenced code blocks replaced by placeholders.
    """

    def _replacer(m: re.Match[str]) -> str:
        idx = len(blocks)
        blocks.append(m.group(0))
        return f"{_PLACEHOLDER_PREFIX}{idx}{_PLACEHOLDER_SUFFIX}"

    return _FENCED_CODE_BLOCK_RE.sub(_replacer, text)


def unprotect_fenced_blocks(text: str, blocks: list[str]) -> str:
    """Restore all fenced code block placeholders with original content.

    Args:
        text: Text containing placeholders.
        blocks: The list of extracted blocks (populated by
            :func:`protect_fenced_blocks`).

    Returns:
        The text with placeholders replaced by original code blocks.
    """
    for i, block in enumerate(blocks):
        text = text.replace(f"{_PLACEHOLDER_PREFIX}{i}{_PLACEHOLDER_SUFFIX}", block)
    return text
