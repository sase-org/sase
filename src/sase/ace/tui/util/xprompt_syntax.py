"""Markdown syntax highlighting with semantic xprompt overlays."""

from __future__ import annotations

import re

from rich.syntax import Syntax
from rich.text import Text

from sase.xprompt._directive_alt import _ALT_DIRECTIVE_RE
from sase.xprompt._directive_types import (
    _DIRECTIVE_ALIASES,
    _DIRECTIVE_PATTERN,
    _KNOWN_DIRECTIVES,
)
from sase.xprompt._disabled_regions import disabled_region_ranges
from sase.xprompt._fenced_blocks import fenced_block_ranges
from sase.xprompt._parsing import (
    find_matching_brace_for_args,
    find_matching_paren_for_args,
)
from sase.xprompt._parsing_references import iter_xprompt_references
from sase.xprompt.segment_separators import _SEGMENT_SEPARATOR_RE

from .lazy_syntax import MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES

XPROMPT_TOKEN_STYLES: dict[str, str] = {
    "invocation": "bold #87D787",
    "invocation_arg": "#5FAF87",
    "directive": "bold #FFD75F",
    "directive_arg": "#D7AF5F",
    "alt_delimiter": "bold #D787FF",
    "separator": "dim bold #87AFFF",
}

_DIRECTIVE_RE = re.compile(_DIRECTIVE_PATTERN, re.MULTILINE)


def _overlaps_protected(
    start: int,
    end: int,
    protected_ranges: list[tuple[int, int]],
) -> bool:
    return any(
        start < protected_end and end > protected_start
        for protected_start, protected_end in protected_ranges
    )


def _directive_end(text: str, match: re.Match[str]) -> int:
    if match.group(2) is None:
        return match.end()
    paren_start = match.end() - 1
    paren_end = find_matching_paren_for_args(text, paren_start)
    return match.end() if paren_end is None else paren_end + 1


def _top_level_pipe_offsets(text: str, start: int, end: int) -> list[int]:
    """Return top-level ``|`` offsets inside one brace alt expression."""
    offsets: list[int] = []
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {
        ")": "(",
        "]": "[",
        "}": "{",
    }
    quote: str | None = None
    escaped = False
    for offset in range(start, end):
        char = text[offset]
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote is not None:
            escaped = True
            continue
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char in depths:
            depths[char] += 1
            continue
        opener = closing.get(char)
        if opener is not None and depths[opener] > 0:
            depths[opener] -= 1
            continue
        if char == "|" and not any(depths.values()):
            offsets.append(offset)
    return offsets


def _apply_xprompt_overlays(text: str, highlighted: Text) -> None:
    protected = sorted([*fenced_block_ranges(text), *disabled_region_ranges(text)])

    for reference in iter_xprompt_references(text):
        if _overlaps_protected(reference.start, reference.end, protected):
            continue
        argument_start = reference.end - len(reference.argument_source)
        highlighted.stylize(
            XPROMPT_TOKEN_STYLES["invocation"],
            reference.start,
            argument_start,
        )
        if argument_start < reference.end:
            highlighted.stylize(
                XPROMPT_TOKEN_STYLES["invocation_arg"],
                argument_start,
                reference.end,
            )

    for match in _DIRECTIVE_RE.finditer(text):
        raw_name = match.group(1)
        name = _DIRECTIVE_ALIASES.get(raw_name, raw_name)
        if name not in _KNOWN_DIRECTIVES:
            continue
        end = _directive_end(text, match)
        if _overlaps_protected(match.start(), end, protected):
            continue
        highlighted.stylize(
            XPROMPT_TOKEN_STYLES["directive"],
            match.start(),
            match.end(1),
        )
        if match.end(1) < end:
            highlighted.stylize(
                XPROMPT_TOKEN_STYLES["directive_arg"],
                match.end(1),
                end,
            )

    for match in _ALT_DIRECTIVE_RE.finditer(text):
        open_pos = match.end() - 1
        close_pos = (
            find_matching_brace_for_args(text, open_pos)
            if text[open_pos] == "{"
            else find_matching_paren_for_args(text, open_pos)
        )
        expression_end = match.end() if close_pos is None else close_pos + 1
        if _overlaps_protected(match.start(), expression_end, protected):
            continue
        highlighted.stylize(
            XPROMPT_TOKEN_STYLES["alt_delimiter"],
            match.start(),
            match.end(),
        )
        if close_pos is None:
            continue
        highlighted.stylize(
            XPROMPT_TOKEN_STYLES["alt_delimiter"], close_pos, close_pos + 1
        )
        if text[open_pos] == "{":
            for pipe_offset in _top_level_pipe_offsets(text, open_pos + 1, close_pos):
                highlighted.stylize(
                    XPROMPT_TOKEN_STYLES["alt_delimiter"],
                    pipe_offset,
                    pipe_offset + 1,
                )

    for match in _SEGMENT_SEPARATOR_RE.finditer(text):
        if _overlaps_protected(match.start(), match.end(), protected):
            continue
        highlighted.stylize(
            XPROMPT_TOKEN_STYLES["separator"], match.start(), match.end()
        )


def highlight_prompt_text(text: str) -> Text:
    """Return Markdown-highlighted prompt text with xprompt token overlays.

    Highlighting is presentation-only and deliberately fail-open: oversized or
    malformed input always remains fully visible as plain text.
    """
    if (
        len(text.encode("utf-8", errors="replace"))
        > MARKDOWN_SYNTAX_HIGHLIGHT_MAX_BYTES
    ):
        return Text(text)
    try:
        highlighted = Syntax(text, "markdown", theme="monokai").highlight(text)
        if not text.endswith("\n") and highlighted.plain.endswith("\n"):
            highlighted.right_crop(1)
        _apply_xprompt_overlays(text, highlighted)
        return highlighted
    except Exception:
        return Text(text)


__all__ = ["XPROMPT_TOKEN_STYLES", "highlight_prompt_text"]
