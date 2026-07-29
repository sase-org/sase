"""Unit tests for preview-reader search and wrapped-row math."""

from __future__ import annotations

import pytest
from rich.console import Console
from rich.segment import Segment
from rich.syntax import Syntax
from rich.text import Text

from sase.ace.tui.modals.preview_search import (
    build_search_result,
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
