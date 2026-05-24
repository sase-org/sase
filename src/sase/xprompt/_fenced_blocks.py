"""Fenced code block protection for xprompt processing.

Provides utilities to extract fenced code blocks from text before xprompt
expansion and restore them afterward, preventing content inside code blocks
from being treated as xprompt references.
"""

from collections.abc import Iterator

_PLACEHOLDER_PREFIX = "\x00XPF_"
_PLACEHOLDER_SUFFIX = "\x00"


def _line_content(line: str) -> str:
    """Return *line* without its trailing line ending."""
    if line.endswith("\n"):
        line = line[:-1]
    if line.endswith("\r"):
        line = line[:-1]
    return line


def _leading_spaces(line: str) -> int | None:
    spaces = 0
    while spaces < len(line) and line[spaces] == " ":
        spaces += 1
        if spaces > 3:
            return None
    return spaces


def _opening_fence(line: str) -> tuple[str, int] | None:
    content = _line_content(line)
    spaces = _leading_spaces(content)
    if spaces is None or spaces == len(content):
        return None

    fence_char = content[spaces]
    if fence_char not in {"`", "~"}:
        return None

    fence_end = spaces
    while fence_end < len(content) and content[fence_end] == fence_char:
        fence_end += 1

    fence_length = fence_end - spaces
    if fence_length < 3:
        return None

    return fence_char, fence_length


def _closing_fence_end(line: str, fence_char: str, fence_length: int) -> int | None:
    content = _line_content(line)
    spaces = _leading_spaces(content)
    if spaces is None or spaces == len(content):
        return None

    fence_start = spaces
    if content[fence_start] != fence_char:
        return None

    fence_end = fence_start
    while fence_end < len(content) and content[fence_end] == fence_char:
        fence_end += 1

    if fence_end - fence_start < fence_length:
        return None

    if content[fence_end:].strip():
        return None

    return fence_end


def _line_ranges(text: str) -> Iterator[tuple[int, int, str]]:
    start = 0
    while start < len(text):
        newline = text.find("\n", start)
        end = len(text) if newline == -1 else newline + 1
        yield start, end, text[start:end]
        start = end


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

    ranges = fenced_block_ranges(text)
    if not ranges:
        return text

    protected_parts: list[str] = []
    cursor = 0
    for start, end in ranges:
        idx = len(blocks)
        blocks.append(text[start:end])
        protected_parts.append(text[cursor:start])
        protected_parts.append(f"{_PLACEHOLDER_PREFIX}{idx}{_PLACEHOLDER_SUFFIX}")
        cursor = end

    protected_parts.append(text[cursor:])
    return "".join(protected_parts)


def fenced_block_ranges(text: str) -> list[tuple[int, int]]:
    """Return (start, end) ranges for all fenced code blocks in *text*.

    Useful when callers need to filter regex matches that fall inside
    fenced code blocks without altering the text (and therefore without
    shifting character offsets).
    """
    ranges: list[tuple[int, int]] = []
    block_start: int | None = None
    fence_char = ""
    fence_length = 0

    for line_start, _line_end, line in _line_ranges(text):
        if block_start is None:
            opening = _opening_fence(line)
            if opening is None:
                continue
            fence_char, fence_length = opening
            block_start = line_start
            continue

        closing_end = _closing_fence_end(line, fence_char, fence_length)
        if closing_end is not None:
            ranges.append((block_start, line_start + closing_end))
            block_start = None

    if block_start is not None:
        ranges.append((block_start, len(text)))

    return ranges


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
