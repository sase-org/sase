"""Code-literal protection for xprompt processing.

Fence discovery is owned by the Rust `fenced_block_details` scanner. This
module converts those UTF-8 byte ranges to Python character offsets and keeps
the established placeholder protect/unprotect API used by launch-time
consumers.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Any


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
    rows = _details_scanner()(text)
    if not isinstance(rows, list):
        return []
    return [_details_from_wire(text, row) for row in rows if isinstance(row, dict)]


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


def _details_from_wire(text: str, row: dict[str, Any]) -> _FencedBlockDetails:
    return _FencedBlockDetails(
        block_range=_pair(text, row.get("block_range")),
        opening_fence=_pair(text, row.get("opening_fence")),
        info_string=_optional_pair(text, row.get("info_string")),
        content_range=_pair(text, row.get("content_range")),
        closing_fence=_optional_pair(text, row.get("closing_fence")),
    )


def _optional_pair(text: str, raw: Any) -> tuple[int, int] | None:
    if raw is None:
        return None
    return _pair(text, raw)


def _pair(text: str, raw: Any) -> tuple[int, int]:
    if not isinstance(raw, list) or len(raw) != 2:
        return (0, 0)
    return _byte_range_to_character(text, int(raw[0]), int(raw[1]))


def _byte_range_to_character(text: str, start: int, end: int) -> tuple[int, int]:
    if text.isascii():
        return start, end
    mapping = _byte_to_character(text)
    return mapping.get(start, start), mapping.get(end, end)


def _byte_to_character(text: str) -> dict[int, int]:
    mapping: dict[int, int] = {}
    byte_offset = 0
    for character_offset, character in enumerate(text):
        mapping[byte_offset] = character_offset
        byte_offset += len(character.encode("utf-8"))
    mapping[byte_offset] = len(text)
    return mapping


@cache
def _details_scanner() -> Callable[..., Any]:
    from sase.core.rust import require_rust_binding

    return require_rust_binding("fenced_block_details")


__all__ = [
    "fenced_block_details",
    "fenced_block_ranges",
    "protect_fenced_blocks",
    "protect_fenced_blocks_only",
    "unprotect_fenced_blocks",
]
