"""Break-only wrapping for Markdown prose."""

from __future__ import annotations

import re
import unicodedata

from sase.markdown_width import MARKDOWN_PRINT_WIDTH

DEFAULT_PROSE_WRAP_WIDTH = MARKDOWN_PRINT_WIDTH
MIN_PROSE_WRAP_WIDTH = 20

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_TABLE_ROW_RE = re.compile(r"^\s*\|")
_LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])(\s+)")
_BLOCKQUOTE_RE = re.compile(r"^(\s*(?:>+\s?)+)")
_ATX_HEADING_RE = re.compile(r"^(\s*)#{1,6}\s+")
_LEADING_SPACE_RE = re.compile(r"^ *")
_BACKTICK_RUN_RE = re.compile(r"`+")

_INLINE_CODE_RE = re.compile(r"(`+)(?:(?!\1).)+?\1")
_MARKDOWN_LINK_RE = re.compile(r'!?\[[^\]]*\]\([^)\s]*(?:\s+"[^"]*")?\)')
_AUTOLINK_RE = re.compile(r"<[^>\s]+>")
_BARE_URL_RE = re.compile(r"(?:https?|ftp|file)://\S+|www\.\S+")
_ATOM_PATTERNS = (
    _INLINE_CODE_RE,
    _MARKDOWN_LINK_RE,
    _AUTOLINK_RE,
    _BARE_URL_RE,
)


def wrap_markdown(text: str, *, width: int) -> str:
    """Wrap over-wide Markdown prose lines without reflowing short lines."""
    if width < MIN_PROSE_WRAP_WIDTH:
        return text

    wrapped_lines: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.split("\n"):
        if fence is not None:
            wrapped_lines.append(line)
            if _is_fence_close(line, fence):
                fence = None
            continue

        fence = _fence_open(line)
        if fence is not None:
            wrapped_lines.append(line)
            continue

        if _line_is_verbatim(line, width=width):
            wrapped_lines.append(line)
            continue

        wrapped_lines.extend(_wrap_line(line, width=width))

    return "\n".join(wrapped_lines)


def _line_is_verbatim(line: str, *, width: int) -> bool:
    if _cell_width(line) <= width:
        return True
    if _TABLE_ROW_RE.match(line):
        return True
    if "\t" in line:
        return True
    if len(_BACKTICK_RUN_RE.findall(line)) % 2 == 1:
        return True
    return _is_indented_code(line)


def _is_indented_code(line: str) -> bool:
    if _LIST_ITEM_RE.match(line) or _BLOCKQUOTE_RE.match(line):
        return False
    return _cell_width(_leading_spaces(line)) >= 4


def _wrap_line(line: str, *, width: int) -> list[str]:
    continuation_prefix = _continuation_prefix(line)
    leading_spaces = _leading_spaces(line)
    if width - _cell_width(continuation_prefix) < MIN_PROSE_WRAP_WIDTH:
        continuation_prefix = leading_spaces
    if width - _cell_width(continuation_prefix) < MIN_PROSE_WRAP_WIDTH:
        return [line]

    atoms, trailing_gap = _atoms_with_gaps(line)
    if not atoms:
        return [line]

    segments: list[str] = []
    current = ""
    for gap, atom in atoms:
        if not current:
            current = f"{gap}{atom}"
            continue
        candidate = f"{current}{gap}{atom}"
        if _cell_width(candidate) <= width:
            current = candidate
            continue
        segments.append(current.rstrip())
        current = f"{continuation_prefix}{atom}"

    if current:
        segments.append(f"{current}{trailing_gap}")
    return segments


def _continuation_prefix(line: str) -> str:
    list_match = _LIST_ITEM_RE.match(line)
    if list_match is not None:
        return " " * _cell_width(list_match.group(0))

    blockquote_match = _BLOCKQUOTE_RE.match(line)
    if blockquote_match is not None:
        return blockquote_match.group(1)

    heading_match = _ATX_HEADING_RE.match(line)
    if heading_match is not None:
        return heading_match.group(1)

    return _leading_spaces(line)


def _atoms_with_gaps(line: str) -> tuple[list[tuple[str, str]], str]:
    atoms: list[tuple[str, str]] = []
    pos = 0
    trailing_gap = ""
    while pos < len(line):
        gap_start = pos
        while pos < len(line) and line[pos].isspace():
            pos += 1
        gap = line[gap_start:pos]
        if pos >= len(line):
            trailing_gap = gap
            break

        atom = _match_atom(line, pos)
        atoms.append((gap, atom))
        pos += len(atom)
    return atoms, trailing_gap


def _match_atom(line: str, pos: int) -> str:
    for pattern in _ATOM_PATTERNS:
        match = pattern.match(line, pos)
        if match is not None:
            return match.group(0)

    end = pos
    while end < len(line) and not line[end].isspace():
        end += 1
    return line[pos:end]


def _fence_open(line: str) -> tuple[str, int] | None:
    match = _FENCE_RE.match(line)
    if match is None:
        return None
    fence = match.group(1)
    return fence[0], len(fence)


def _is_fence_close(line: str, fence: tuple[str, int]) -> bool:
    char, minimum = fence
    match = _FENCE_RE.match(line)
    return (
        match is not None
        and match.group(1)[0] == char
        and len(match.group(1)) >= minimum
    )


def _leading_spaces(line: str) -> str:
    match = _LEADING_SPACE_RE.match(line)
    assert match is not None
    return match.group(0)


def _cell_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


__all__ = [
    "DEFAULT_PROSE_WRAP_WIDTH",
    "MIN_PROSE_WRAP_WIDTH",
    "wrap_markdown",
]
