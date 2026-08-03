"""Unit coverage for Markdown-aware prose wrapping."""

from __future__ import annotations

import unicodedata

import pytest

from sase.file_references import DEFAULT_MARKDOWN_WRAP_WIDTH
from sase.markdown_wrap import (
    DEFAULT_PROSE_WRAP_WIDTH,
    MIN_PROSE_WRAP_WIDTH,
    wrap_markdown,
)


def _cell_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


_CORPUS = [
    "one two three four five six seven eight nine ten",
    "- one two three four five six seven eight nine ten",
    "  1) one two three four five six seven eight nine ten",
    "# Heading one two three four five six seven eight nine ten",
    "prefix `foo bar baz` suffix more words here",
    "[some text](https://example.com/very/long) more words words words",
    "CJK words: 界 界 界 界 界 界 界 界 界 界 界",
]


@pytest.mark.parametrize("width", [20, 40, 80, 120])
@pytest.mark.parametrize("text", _CORPUS)
def test_wrap_preserves_content_and_is_idempotent(text: str, width: int) -> None:
    wrapped = wrap_markdown(text, width=width)

    assert "".join(wrapped.split()) == "".join(text.split())
    assert wrap_markdown(wrapped, width=width) == wrapped


def test_short_lines_are_returned_byte_for_byte() -> None:
    text = "short line\n  already indented\n- short bullet\n"

    assert wrap_markdown(text, width=120) == text


def test_wrapped_ascii_lines_honor_width() -> None:
    text = "one two three four five six seven eight nine ten"

    wrapped = wrap_markdown(text, width=20)

    assert all(len(line) <= 20 for line in wrapped.split("\n"))


def test_url_atom_is_never_split() -> None:
    url = f"https://example.com/{'a' * 150}"
    text = f"See {url} after the link for more words."

    wrapped = wrap_markdown(text, width=40)

    assert url in wrapped.split()


def test_inline_code_atoms_are_never_split() -> None:
    text = "prefix words `foo bar baz` suffix words words words"
    double_tick = "prefix words ``a ` b`` suffix words words words"

    assert any(
        "`foo bar baz`" in line for line in wrap_markdown(text, width=20).split("\n")
    )
    assert any(
        "``a ` b``" in line for line in wrap_markdown(double_tick, width=20).split("\n")
    )


def test_unbalanced_inline_code_line_is_verbatim() -> None:
    text = "prefix `unterminated code span with many words that would wrap"

    assert wrap_markdown(text, width=30) == text


def test_markdown_link_atom_is_never_split() -> None:
    link = "[some text](https://example.com/very/long)"
    text = f"Before {link} after words words words."

    wrapped = wrap_markdown(text, width=30)

    assert any(link in line for line in wrapped.split("\n"))


def test_code_fences_are_verbatim() -> None:
    text = (
        "before words words words words words\n"
        "```python\n"
        "this code line is intentionally much longer than the budget\n"
        "```\n"
        "~~~\n"
        "another long code line that is intentionally untouched\n"
        "~~~"
    )

    wrapped = wrap_markdown(text, width=30)

    assert "this code line is intentionally much longer than the budget" in wrapped
    assert "another long code line that is intentionally untouched" in wrapped


def test_unterminated_code_fence_leaves_rest_verbatim() -> None:
    text = "```python\nlong code line that is intentionally much longer than width"

    assert wrap_markdown(text, width=30) == text


def test_tables_and_tab_bearing_lines_are_verbatim() -> None:
    table = "| column one | column two | column three | column four |"
    tabbed = "alpha\tbeta gamma delta epsilon zeta eta theta"

    assert wrap_markdown(table, width=30) == table
    assert wrap_markdown(tabbed, width=30) == tabbed


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "- one two three four five six seven eight nine ten",
            "- one two three four five six\n  seven eight nine ten",
        ),
        (
            "* one two three four five six seven eight nine ten",
            "* one two three four five six\n  seven eight nine ten",
        ),
        (
            "+ one two three four five six seven eight nine ten",
            "+ one two three four five six\n  seven eight nine ten",
        ),
        (
            "1. one two three four five six seven eight nine ten",
            "1. one two three four five six\n   seven eight nine ten",
        ),
        (
            "1) one two three four five six seven eight nine ten",
            "1) one two three four five six\n   seven eight nine ten",
        ),
        (
            "  - nested one two three four five six seven eight nine",
            "  - nested one two three four\n    five six seven eight nine",
        ),
        (
            "> quote one two three four five six seven eight nine",
            "> quote one two three four\n> five six seven eight nine",
        ),
        (
            "# Heading one two three four five six seven eight nine",
            "# Heading one two three four\nfive six seven eight nine",
        ),
    ],
)
def test_continuation_prefixes(text: str, expected: str) -> None:
    assert wrap_markdown(text, width=30) == expected


def test_wide_character_columns_are_measured() -> None:
    text = "界 界 界 界 界 界 界 界 界 界 界"

    wrapped = wrap_markdown(text, width=20)

    assert wrapped == "界 界 界 界 界 界 界\n界 界 界 界"
    assert all(_cell_width(line) <= 20 for line in wrapped.split("\n"))


def test_degenerate_inputs() -> None:
    assert wrap_markdown("", width=20) == ""
    assert wrap_markdown("     ", width=20) == "     "
    assert (
        wrap_markdown("one two three", width=MIN_PROSE_WRAP_WIDTH - 1)
        == "one two three"
    )


def test_single_overwide_atom_overflows_without_splitting() -> None:
    atom = "x" * 80
    text = f"prefix {atom} suffix"

    wrapped = wrap_markdown(text, width=30)

    assert atom in wrapped.split()


def test_final_trailing_whitespace_is_preserved() -> None:
    text = "one two three four five six seven eight  "

    wrapped = wrap_markdown(text, width=20)

    assert wrapped.endswith("  ")


def test_default_width_matches_markdown_file_formatting_default() -> None:
    assert DEFAULT_PROSE_WRAP_WIDTH == DEFAULT_MARKDOWN_WRAP_WIDTH
