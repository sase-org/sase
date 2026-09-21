"""Unit tests for preview-reader search and wrapped-row math."""

from __future__ import annotations

import pytest
from rich.console import Console
from rich.segment import Segment
from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.modals.preview_search import (
    build_search_result,
    count_wrapped_rows,
    _find_match_lines,
    _wrapped_row_offsets,
)
from sase.ace.tui.util.lazy_syntax import MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES


def test_find_match_lines_uses_smartcase_substrings() -> None:
    content = "Alpha beta\nalpha BETA\nalphabet soup\nunrelated"

    assert _find_match_lines(content, "alpha") == (1, 2, 3)
    assert _find_match_lines(content, "Alpha") == (1,)
    assert _find_match_lines(content, "BETA") == (2,)
    assert _find_match_lines(content, "") == ()


@pytest.mark.parametrize("width", [12, 20, 37])
@pytest.mark.parametrize(
    "content",
    [
        "short\naveryveryverylongunbrokentoken\nend",
        "wide 漢字🙂🙂🙂 text\nplain\nmore 漢字",
        "tabs\talign\there\n\tindented\nlast",
    ],
)
def test_wrapped_row_offsets_agree_with_rich_syntax_render(
    width: int,
    content: str,
) -> None:
    offsets = _wrapped_row_offsets(content, width)
    console = Console(width=width, force_terminal=True)
    syntax = Syntax(
        content,
        "text",
        line_numbers=True,
        word_wrap=True,
        tab_size=4,
    )
    rendered_lines = list(Segment.split_lines(console.render(syntax)))
    actual_offsets: list[int] = []
    for row_index, line in enumerate(rendered_lines):
        row = list(line)
        if len(row) >= 2 and row[0].text == "  " and row[1].text.strip().isdigit():
            actual_offsets.append(row_index)

    assert offsets == tuple(actual_offsets)


def test_plain_render_offsets_include_wrapped_notice_and_drop_number_gutter() -> None:
    content = "\n".join(["match", *["line"] * MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES])
    width = 20
    result = build_search_result(content, "match", width, "markdown")
    console = Console(width=width, force_terminal=True)
    notice_rows = len(
        Text("Large output rendered without syntax highlighting\n").wrap(
            console,
            width,
        )
    )

    assert result.row_offsets[0] == notice_rows
    assert result.row_offsets[1] == notice_rows + 1


def test_count_wrapped_rows_agrees_with_offsets() -> None:
    content = "short\naveryveryverylongunbrokentoken\nend"
    width = 20
    result = build_search_result(content, "short", width, "text")
    # Total rows = last offset + wrapped height of the final line.
    last_offset = result.row_offsets[-1]
    console = Console(width=width, force_terminal=True)
    from sase.ace.tui.modals.preview_search import _syntax_code_width

    code_width = _syntax_code_width(content, width)
    final_wrapped = Text("end").wrap(console, code_width, overflow="fold")
    total = last_offset + max(1, len(final_wrapped))
    assert count_wrapped_rows(content, width, "text", limit=1000) == total


def test_count_wrapped_rows_early_exits_at_limit() -> None:
    content = "\n".join(f"line {idx}" for idx in range(200))
    assert count_wrapped_rows(content, 40, "python", limit=20) == 21
    # Logical line count fast path: 200 lines without wrapping.
    assert count_wrapped_rows(content, 40, "python", limit=50) == 51


def test_count_wrapped_rows_includes_plain_notice() -> None:
    content = "\n".join(["match", *["line"] * MARKDOWN_SYNTAX_HIGHLIGHT_MAX_LINES])
    width = 20
    result = build_search_result(content, "match", width, "markdown")
    console = Console(width=width, force_terminal=True)
    notice_rows = max(
        1,
        len(
            Text("Large output rendered without syntax highlighting\n").wrap(
                console, width
            )
        ),
    )
    # Small limit still exceeds because of the notice plus many lines.
    assert count_wrapped_rows(content, width, "markdown", limit=5) == 6
    # Large limit agrees with the offset model (notice + one row per line).
    total = notice_rows + len(content.splitlines())
    assert count_wrapped_rows(content, width, "markdown", limit=10000) == total
    assert result.row_offsets[0] == notice_rows
