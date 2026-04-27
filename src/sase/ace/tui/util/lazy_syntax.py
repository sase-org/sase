"""Lazy / capped Rich Syntax rendering (Phase 6).

Building a Rich ``Syntax`` for very large content is expensive — the lexer
walks every byte and the highlighted output is held in memory. For TUI hot
paths (prompt panel, file panel, axe dashboard) we cap the size at which
syntax highlighting is applied and fall back to a plain ``Text`` block with
a small notice when content exceeds the cap. Diff trimming is preserved by
counting only the visible/trimmed range against the cap.
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text

SYNTAX_HIGHLIGHT_MAX_BYTES = 64_000
SYNTAX_HIGHLIGHT_MAX_LINES = 1_500


def _measure(content: str, line_range: tuple[int, int] | None) -> tuple[int, int]:
    """Return ``(byte_size, line_count)`` for the visible portion of content."""
    if line_range is None:
        return len(content.encode("utf-8", errors="replace")), content.count("\n") + 1

    start, end = line_range
    if start < 1:
        start = 1
    lines = content.split("\n")
    if end > len(lines):
        end = len(lines)
    visible = "\n".join(lines[start - 1 : end])
    return len(visible.encode("utf-8", errors="replace")), max(0, end - start + 1)


def _exceeds_cap(content: str, line_range: tuple[int, int] | None = None) -> bool:
    """Return True when content exceeds the syntax-highlight caps."""
    byte_size, line_count = _measure(content, line_range)
    return (
        byte_size > SYNTAX_HIGHLIGHT_MAX_BYTES
        or line_count > SYNTAX_HIGHLIGHT_MAX_LINES
    )


def lazy_renderable(
    content: str,
    lexer: str,
    *,
    line_range: tuple[int, int] | None = None,
    line_numbers: bool = False,
    word_wrap: bool = True,
    theme: str = "monokai",
) -> RenderableType:
    """Return a Rich ``Syntax`` when small enough, else a capped plain block.

    When ``content`` exceeds either cap, render a ``Text`` of the (visible)
    portion preceded by a one-line dim-italic notice. ``line_range`` lets
    diff/file panels measure only the trimmed range so partial views stay on
    the highlighted path even when the underlying file is huge.
    """
    if not _exceeds_cap(content, line_range):
        return Syntax(
            content,
            lexer,
            theme=theme,
            word_wrap=word_wrap,
            line_numbers=line_numbers,
            line_range=line_range,
        )

    notice = Text(
        "Large output rendered without syntax highlighting\n",
        style="dim italic #87D7FF",
    )
    if line_range is not None:
        start, end = line_range
        lines = content.split("\n")
        if start < 1:
            start = 1
        if end > len(lines):
            end = len(lines)
        visible = "\n".join(lines[start - 1 : end])
    else:
        visible = content
    return Group(notice, Text(visible, no_wrap=False))


def cap_ansi_output(output: str) -> str:
    """Cap ANSI-rich output to the configured byte budget (tail-biased).

    Tools that render append-only logs (axe dashboard, lumberjack output)
    keep working when the underlying log grows huge, but rendering the entire
    log through ``Text.from_ansi`` is expensive. We bound the work by keeping
    only the last ``SYNTAX_HIGHLIGHT_MAX_BYTES`` bytes — logs are tail-shaped
    so the head is rarely interesting.
    """
    if len(output) <= SYNTAX_HIGHLIGHT_MAX_BYTES:
        return output
    truncated = output[-SYNTAX_HIGHLIGHT_MAX_BYTES:]
    notice = "[…earlier output truncated to keep rendering fast…]\n"
    return notice + truncated
