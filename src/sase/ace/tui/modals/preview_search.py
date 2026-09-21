"""Pure search and wrapped-row helpers for the preview reader."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from rich.console import Console
from rich.text import Text

from sase.ace.tui.util.lazy_syntax import (
    PLAIN_RENDER_MAX_LINES,
    exceeds_plain_render_cap,
    exceeds_syntax_highlight_cap,
    truncate_plain_content,
)


@dataclass(frozen=True)
class PreviewSearchResult:
    """Search matches and their zero-based wrapped-row offsets."""

    match_lines: tuple[int, ...]
    row_offsets: tuple[int, ...]
    displayed_line_count: int


def _find_match_lines(content: str, query: str) -> tuple[int, ...]:
    """Return one-based lines containing ``query`` using smartcase matching."""
    if not query:
        return ()
    case_sensitive = any(character.isupper() for character in query)
    needle = query if case_sensitive else query.casefold()
    matches: list[int] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        haystack = line if case_sensitive else line.casefold()
        if needle in haystack:
            matches.append(line_number)
    return tuple(matches)


def _syntax_code_width(content: str, available_width: int) -> int:
    """Return Rich Syntax's code width after its line-number gutter."""
    line_count = max(1, content.count("\n") + 1)
    numbers_column_width = len(str(line_count)) + 2
    return max(1, available_width - numbers_column_width - 1)


def _split_logical_lines(content: str, *, tab_size: int = 4) -> list[str]:
    """Split ``content`` the way Rich ``Syntax`` counts logical lines."""
    lines = content.expandtabs(tab_size).split("\n")
    if content.endswith("\n"):
        lines = lines[:-1]
    if not lines:
        lines = [""]
    return lines


def _plain_notice_rows(available_width: int) -> int:
    """Return the wrapped height of the plain-render notice row."""
    console = Console(width=max(1, available_width), force_terminal=True)
    notice = Text("Large output rendered without syntax highlighting\n")
    return max(1, len(notice.wrap(console, max(1, available_width))))


def _iter_wrapped_counts(
    lines: list[str],
    console: Console,
    code_width: int,
    *,
    tab_size: int = 4,
) -> Iterator[int]:
    """Yield the wrapped-row count for each logical line."""
    for line in lines:
        wrapped = Text(line).wrap(
            console,
            code_width,
            overflow="fold",
            tab_size=tab_size,
        )
        yield max(1, len(wrapped))


def _wrapped_row_offsets(
    content: str,
    available_width: int,
    *,
    tab_size: int = 4,
    line_numbers: bool = True,
    initial_rows: int = 0,
) -> tuple[int, ...]:
    """Return the cumulative rendered-row offset for every source line."""
    console = Console(width=max(1, available_width), force_terminal=True)
    code_width = (
        _syntax_code_width(content, available_width)
        if line_numbers
        else max(1, available_width)
    )
    offsets: list[int] = []
    row = initial_rows
    # ``Syntax`` ensures a final logical line while processing its code.
    lines = _split_logical_lines(content, tab_size=tab_size)
    for count in _iter_wrapped_counts(lines, console, code_width, tab_size=tab_size):
        offsets.append(row)
        row += count
    return tuple(offsets)


def count_wrapped_rows(
    content: str,
    available_width: int,
    lexer: str,
    *,
    limit: int,
) -> int:
    """Count wrapped body rows, stopping early once the total exceeds ``limit``.

    Shares the wrap model with :func:`build_search_result` (notice row,
    line-number gutter, tab expansion). Returns ``limit + 1`` when the content
    needs more than ``limit`` rows, so callers can clamp to a maximum without
    wrapping thousands of lines.
    """
    width = max(1, available_width)
    plain_rendering = exceeds_syntax_highlight_cap(content, lexer)
    initial_rows = _plain_notice_rows(width) if plain_rendering else 0
    if initial_rows > limit:
        return limit + 1
    lines = _split_logical_lines(content)
    if initial_rows + len(lines) > limit:
        return limit + 1
    console = Console(width=width, force_terminal=True)
    code_width = _syntax_code_width(content, width) if not plain_rendering else width
    total = initial_rows
    for count in _iter_wrapped_counts(lines, console, code_width):
        total += count
        if total > limit:
            return limit + 1
    return total


def build_search_result(
    content: str,
    query: str,
    available_width: int,
    lexer: str,
) -> PreviewSearchResult:
    """Compute match lines and wrapped-row offsets in one worker-friendly pass."""
    plain_rendering = exceeds_syntax_highlight_cap(content, lexer)
    initial_rows = _plain_notice_rows(available_width) if plain_rendering else 0
    if exceeds_plain_render_cap(content):
        rendered_content, *_rest = truncate_plain_content(
            content,
            max_lines=PLAIN_RENDER_MAX_LINES,
        )
        displayed_line_count = max(1, rendered_content.count("\n") + 1)
    else:
        displayed_line_count = max(1, content.count("\n") + 1)
    return PreviewSearchResult(
        match_lines=_find_match_lines(content, query),
        row_offsets=_wrapped_row_offsets(
            content,
            available_width,
            line_numbers=not plain_rendering,
            initial_rows=initial_rows,
        ),
        displayed_line_count=displayed_line_count,
    )


__all__ = [
    "PreviewSearchResult",
    "build_search_result",
    "count_wrapped_rows",
]
