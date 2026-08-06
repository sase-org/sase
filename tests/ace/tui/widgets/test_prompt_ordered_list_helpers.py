"""Shared list-marker primitives and ordered-marker helper coverage."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets._prompt_bullet_editing import prompt_bullet_sibling_prefix
from sase.ace.tui.widgets._prompt_list_markers import (
    MarkerFamily,
    find_list_marker,
    is_list_boundary_line,
    leading_space_count,
    list_marker_owner,
    owned_block_end,
)
from sase.ace.tui.widgets._prompt_ordered_editing import (
    _is_prompt_ordered_content_column,
    _is_prompt_ordered_marker_only,
    _prompt_ordered_row_has_item_above,
    strip_prompt_ordered_marker,
)

HYPHEN = MarkerFamily.HYPHEN
ORDERED = MarkerFamily.ORDERED


@pytest.mark.parametrize(
    ("line", "indent", "number", "delimiter", "content_column"),
    [
        ("1. item", 0, 1, ".", 3),
        ("1) item", 0, 1, ")", 3),
        ("  12. item", 2, 12, ".", 6),
        ("007. item", 0, 7, ".", 5),
        ("999999999. item", 0, 999999999, ".", 11),
        ("3.  extra spaces are content", 0, 3, ".", 3),
        ("4. ", 0, 4, ".", 3),
    ],
    ids=[
        "dot",
        "paren",
        "indented-multi-digit",
        "leading-zeros",
        "nine-digits",
        "extra-space",
        "marker-only",
    ],
)
def test_find_ordered_marker_fields(
    line: str,
    indent: int,
    number: int,
    delimiter: str,
    content_column: int,
) -> None:
    marker = find_list_marker(line, ORDERED, row=7)

    assert marker is not None
    assert marker.row == 7
    assert marker.indent == indent
    assert marker.number == number
    assert marker.delimiter == delimiter
    assert marker.content_column == content_column
    assert marker.family is ORDERED
    assert line.startswith(marker.text)


@pytest.mark.parametrize(
    "line",
    [
        "1.item",
        "1.",
        "- item",
        "* item",
        "\t1. item",
        "1234567890. item",
        "prose 1. item",
        "",
    ],
    ids=[
        "tight",
        "bare-marker",
        "hyphen",
        "star",
        "tab-indented",
        "ten-digits",
        "mid-prose",
        "empty",
    ],
)
def test_find_ordered_marker_rejects(line: str) -> None:
    assert find_list_marker(line, ORDERED) is None


def test_find_hyphen_marker_fields() -> None:
    marker = find_list_marker("  - item", HYPHEN)

    assert marker is not None
    assert marker.indent == 2
    assert marker.content_column == 4
    assert marker.text == "  - "


@pytest.mark.parametrize(
    ("line", "hyphen_boundary", "ordered_boundary"),
    [
        ("", True, True),
        ("   ", True, True),
        ("\t- item", True, True),
        ("```python", True, True),
        ("~~~", True, True),
        ("---", True, True),
        ("> quote", True, True),
        (">", True, True),
        ("* item", True, True),
        ("+ item", True, True),
        ("- item", False, True),
        ("-", True, True),
        ("1. item", True, False),
        ("1.item", False, True),
        ("1234567890. item", True, True),
        ("plain prose", False, False),
        ("  continuation", False, False),
    ],
    ids=[
        "blank",
        "whitespace",
        "tab",
        "fence",
        "tilde-fence",
        "thematic-break",
        "blockquote",
        "bare-blockquote",
        "star",
        "plus",
        "hyphen-marker",
        "tight-dash",
        "ordered-marker",
        "tight-ordered",
        "ten-digit-ordered",
        "prose",
        "indented-prose",
    ],
)
def test_is_list_boundary_line(
    line: str,
    hyphen_boundary: bool,
    ordered_boundary: bool,
) -> None:
    assert is_list_boundary_line(line, HYPHEN) is hyphen_boundary
    assert is_list_boundary_line(line, ORDERED) is ordered_boundary


@pytest.mark.parametrize(
    ("line", "expected"),
    [("    x", 4), ("x", 0), ("", 0), ("  ", 2)],
    ids=["indented", "flush", "empty", "spaces-only"],
)
def test_leading_space_count(line: str, expected: int) -> None:
    assert leading_space_count(line) == expected


def test_ordered_owner_on_marker_row() -> None:
    lines = ["1. one", "2. two"]

    owner = list_marker_owner(lines, 1, ORDERED)

    assert owner is not None
    assert owner.row == 1
    assert owner.number == 2


def test_ordered_owner_covers_continuation_lines() -> None:
    lines = ["10. one", "    wrapped prose", "    still wrapped"]

    owner = list_marker_owner(lines, 2, ORDERED)

    assert owner is not None
    assert owner.row == 0
    assert owner.content_column == 4


def test_ordered_owner_rejects_under_indented_continuation() -> None:
    lines = ["10. one", "   under indented"]

    assert list_marker_owner(lines, 1, ORDERED) is None


def test_ordered_owner_stops_at_blank_line() -> None:
    lines = ["1. one", "", "   orphan"]

    assert list_marker_owner(lines, 2, ORDERED) is None


def test_ordered_owner_stops_at_fence() -> None:
    lines = ["1. one", "   ```", "   code"]

    assert list_marker_owner(lines, 2, ORDERED) is None


def test_families_do_not_own_each_others_lines() -> None:
    lines = ["- bullet", "  1. ordered", "     wrapped"]

    ordered_owner = list_marker_owner(lines, 2, ORDERED)
    hyphen_owner = list_marker_owner(lines, 2, HYPHEN)

    assert ordered_owner is not None
    assert ordered_owner.row == 1
    assert hyphen_owner is None


def test_ordered_marker_is_still_a_hyphen_boundary() -> None:
    lines = ["- bullet", "  1. ordered"]

    assert prompt_bullet_sibling_prefix(lines, 1) is None


def test_owned_block_end_covers_continuations_only() -> None:
    lines = ["1. one", "   wrapped", "   more", "2. two"]

    marker = find_list_marker(lines[0], ORDERED, row=0)

    assert marker is not None
    assert owned_block_end(lines, marker) == 2


def test_owned_block_end_is_the_marker_row_when_nothing_is_owned() -> None:
    lines = ["1. one", "2. two"]

    marker = find_list_marker(lines[0], ORDERED, row=0)

    assert marker is not None
    assert owned_block_end(lines, marker) == 0


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("1. ", True),
        ("  12. ", True),
        ("1) ", True),
        ("1. item", False),
        ("1.", False),
        ("1.  ", False),
        ("- ", False),
        ("", False),
        ("\t1. ", False),
    ],
    ids=[
        "top-level",
        "nested",
        "paren",
        "content",
        "tight",
        "extra-space",
        "hyphen",
        "empty",
        "tab",
    ],
)
def test_is_prompt_ordered_marker_only(line: str, expected: bool) -> None:
    assert _is_prompt_ordered_marker_only(line) is expected


@pytest.mark.parametrize(
    ("line", "cursor_col", "expected"),
    [
        ("1. item", 3, True),
        ("  10. item", 6, True),
        ("1. item", 2, False),
        ("1. item", 4, False),
        ("- item", 2, False),
        ("\t1. item", 3, False),
    ],
    ids=[
        "content-column",
        "nested-content-column",
        "before",
        "after",
        "hyphen",
        "tab",
    ],
)
def test_is_prompt_ordered_content_column(
    line: str,
    cursor_col: int,
    expected: bool,
) -> None:
    assert _is_prompt_ordered_content_column(line, cursor_col) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("1. item", "item"),
        ("  10) item", "item"),
        ("1.  double", " double"),
        ("1.tight", "1.tight"),
        ("- item", "- item"),
        ("\t1. item", "\t1. item"),
        ("plain", "plain"),
    ],
    ids=[
        "top-level",
        "nested-paren",
        "extra-space",
        "tight",
        "hyphen",
        "tab",
        "prose",
    ],
)
def test_strip_prompt_ordered_marker(line: str, expected: str) -> None:
    assert strip_prompt_ordered_marker(line) == expected


@pytest.mark.parametrize(
    ("lines", "row", "expected"),
    [
        (["1. one", "2. "], 1, True),
        (["1. one", "   wrapped", "2. "], 2, True),
        (["1. "], 0, False),
        (["", "1. "], 1, False),
        (["- one", "1. "], 1, False),
    ],
    ids=[
        "item-above",
        "continuation-above",
        "first-row",
        "blank-above",
        "hyphen-above",
    ],
)
def test_prompt_ordered_row_has_item_above(
    lines: list[str],
    row: int,
    expected: bool,
) -> None:
    assert _prompt_ordered_row_has_item_above(lines, row) is expected
