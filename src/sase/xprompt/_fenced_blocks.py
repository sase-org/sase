"""Code-literal protection for xprompt processing.

The legacy ``protect_fenced_blocks`` API now protects both fenced blocks and
single-line inline code. Keeping that behavior behind the established
primitive makes every launch-time consumer share one literal-zone scanner.
"""

from collections.abc import Iterator
from dataclasses import dataclass

_PLACEHOLDER_PREFIX = "\x00XPF_"
_PLACEHOLDER_SUFFIX = "\x00"


@dataclass(frozen=True, slots=True)
class _FencedBlockDetails:
    """Structured source ranges for one fenced code block."""

    block_range: tuple[int, int]
    opening_fence: tuple[int, int]
    info_string: tuple[int, int] | None
    content_range: tuple[int, int]
    closing_fence: tuple[int, int] | None


@dataclass(frozen=True, slots=True)
class _OpeningFence:
    char: str
    length: int
    run_start: int
    run_end: int
    info_string: tuple[int, int] | None


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


def _opening_fence(line: str) -> _OpeningFence | None:
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

    info_start = fence_end
    while info_start < len(content) and content[info_start].isspace():
        info_start += 1
    info_end = len(content.rstrip())
    info_string = (info_start, info_end) if info_start < info_end else None
    return _OpeningFence(
        char=fence_char,
        length=fence_length,
        run_start=spaces,
        run_end=fence_end,
        info_string=info_string,
    )


def _closing_fence_span(
    line: str, fence_char: str, fence_length: int
) -> tuple[int, int] | None:
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

    return fence_start, fence_end


def _line_ranges(text: str) -> Iterator[tuple[int, int, str]]:
    start = 0
    while start < len(text):
        newline = text.find("\n", start)
        end = len(text) if newline == -1 else newline + 1
        yield start, end, text[start:end]
        start = end


def _protect_ranges(
    text: str,
    blocks: list[str],
    ranges: list[tuple[int, int]],
) -> str:
    """Replace *ranges* with placeholders backed by ``blocks``."""
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


def protect_fenced_blocks(text: str, blocks: list[str]) -> str:
    """Replace fenced and inline code with null-byte placeholders.

    Each extracted block is appended to ``blocks``, using the list length
    as the starting index for placeholder numbering.  This allows the
    function to be called multiple times (e.g. once before the expansion
    loop and again after each iteration) without placeholder collisions.

    Args:
        text: The text to scan for fenced and inline code.
        blocks: Mutable list that accumulates extracted literal content.

    Returns:
        The text with code literal zones replaced by placeholders.
    """

    from ._literal_zones import code_literal_ranges

    return _protect_ranges(text, blocks, code_literal_ranges(text))


def protect_fenced_blocks_only(text: str, blocks: list[str]) -> str:
    """Replace fenced code blocks, but not inline code, with placeholders."""
    return _protect_ranges(text, blocks, fenced_block_ranges(text))


def fenced_block_ranges(text: str) -> list[tuple[int, int]]:
    """Return (start, end) ranges for all fenced code blocks in *text*.

    Useful when callers need to filter regex matches that fall inside
    fenced code blocks without altering the text (and therefore without
    shifting character offsets).
    """
    return [details.block_range for details in fenced_block_details(text)]


def fenced_block_details(text: str) -> list[_FencedBlockDetails]:
    """Return structured ranges for every closed or live unclosed fence."""
    details: list[_FencedBlockDetails] = []
    block_start: int | None = None
    content_start = 0
    opening_fence = (0, 0)
    info_string: tuple[int, int] | None = None
    fence_char = ""
    fence_length = 0

    for line_start, line_end, line in _line_ranges(text):
        if block_start is None:
            opening = _opening_fence(line)
            if opening is None:
                continue
            fence_char = opening.char
            fence_length = opening.length
            block_start = line_start
            content_start = line_end
            opening_fence = (
                line_start + opening.run_start,
                line_start + opening.run_end,
            )
            info_string = (
                (
                    line_start + opening.info_string[0],
                    line_start + opening.info_string[1],
                )
                if opening.info_string is not None
                else None
            )
            continue

        closing = _closing_fence_span(line, fence_char, fence_length)
        if closing is None:
            continue
        closing_fence = (line_start + closing[0], line_start + closing[1])
        details.append(
            _FencedBlockDetails(
                block_range=(block_start, closing_fence[1]),
                opening_fence=opening_fence,
                info_string=info_string,
                content_range=(content_start, line_start),
                closing_fence=closing_fence,
            )
        )
        block_start = None

    if block_start is not None:
        details.append(
            _FencedBlockDetails(
                block_range=(block_start, len(text)),
                opening_fence=opening_fence,
                info_string=info_string,
                content_range=(content_start, len(text)),
                closing_fence=None,
            )
        )

    return details


def unprotect_fenced_blocks(text: str, blocks: list[str]) -> str:
    """Restore all fenced and inline code placeholders with original content.

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


__all__ = [
    "fenced_block_details",
    "fenced_block_ranges",
    "protect_fenced_blocks",
    "protect_fenced_blocks_only",
    "unprotect_fenced_blocks",
]
