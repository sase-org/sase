"""Prompt hyphen-bullet ownership and helper coverage."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets._prompt_bullet_editing import (
    is_prompt_bullet_marker_only,
    normalize_prompt_bullet_replay_text,
    plan_prompt_bullet_shift,
    prompt_bullet_row_has_bullet_above,
    prompt_bullet_sibling_prefix,
    strip_prompt_bullet_marker,
)
from sase.ace.tui.widgets._paired_text_editing import TextEdit


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("- ", True),
        ("  - ", True),
        ("- item", False),
        ("  - item", False),
        ("-", False),
        ("-  ", False),
        ("", False),
        ("   ", False),
        ("* ", False),
        ("+ ", False),
        ("1. ", False),
        ("> ", False),
        ("\t- ", False),
        (" \t- ", False),
    ],
    ids=[
        "top-level",
        "nested",
        "content",
        "nested-content",
        "tight-dash",
        "extra-space",
        "empty",
        "whitespace",
        "asterisk",
        "plus",
        "ordered",
        "blockquote",
        "tab",
        "space-tab",
    ],
)
def test_is_prompt_bullet_marker_only(line: str, expected: bool) -> None:
    assert is_prompt_bullet_marker_only(line) is expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("- x", "x"),
        ("  - x", "x"),
        ("-   x", "  x"),
        ("- ", ""),
        ("  - ", ""),
        ("-x", "-x"),
        ("-", "-"),
        ("\t- x", "\t- x"),
        (" \t- x", " \t- x"),
        ("* x", "* x"),
        ("+ x", "+ x"),
        ("1. x", "1. x"),
        ("> x", "> x"),
        ("- - -", "- - -"),
        ("---", "---"),
        ("", ""),
        ("   ", "   "),
        ("plain", "plain"),
    ],
    ids=[
        "top-level",
        "nested",
        "extra-content-space",
        "marker-only",
        "nested-marker-only",
        "tight-dash",
        "dash-only",
        "tab-indented",
        "space-tab-indented",
        "asterisk",
        "plus",
        "ordered",
        "blockquote",
        "thematic-break-spaced",
        "thematic-break-tight",
        "empty",
        "whitespace",
        "plain",
    ],
)
def test_strip_prompt_bullet_marker(line: str, expected: str) -> None:
    assert strip_prompt_bullet_marker(line) == expected


@pytest.mark.parametrize(
    ("text", "offset", "expected"),
    [
        ("- item", 0, TextEdit(start=0, end=0, text="  ", cursor=2)),
        ("- ", 2, TextEdit(start=0, end=0, text="  ", cursor=4)),
        ("  - item", 0, TextEdit(start=0, end=0, text="  ", cursor=2)),
        ("  - item", 1, TextEdit(start=0, end=0, text="  ", cursor=3)),
        ("  - item", 2, TextEdit(start=0, end=0, text="  ", cursor=4)),
        ("  - item", 4, TextEdit(start=0, end=0, text="  ", cursor=6)),
        (
            "intro\n  - item",
            10,
            TextEdit(start=6, end=6, text="  ", cursor=12),
        ),
        ("- item", 3, None),
        ("plain prose", 0, None),
        ("\t- item", 2, None),
        ("* item", 2, None),
        ("+ item", 2, None),
        ("1. item", 3, None),
        ("> item", 2, None),
        ("-tight", 1, None),
        ("-", 1, None),
        ("---", 0, None),
        ("- item\n  wrapped", 9, None),
    ],
    ids=[
        "top-level-dash",
        "marker-only-content",
        "nested-column-zero",
        "inside-indentation",
        "on-dash",
        "content-column",
        "later-row-offset",
        "past-content-column",
        "prose",
        "tab-indented",
        "asterisk",
        "plus",
        "ordered",
        "blockquote",
        "tight-dash",
        "dash-without-space",
        "thematic-break",
        "physical-continuation",
    ],
)
def test_plan_prompt_bullet_indent(
    text: str,
    offset: int,
    expected: TextEdit | None,
) -> None:
    assert plan_prompt_bullet_shift(text, offset, dedent=False) == expected


@pytest.mark.parametrize(
    ("text", "offset", "expected"),
    [
        ("    - item", 0, TextEdit(start=0, end=2, text="", cursor=0)),
        ("    - item", 1, TextEdit(start=0, end=2, text="", cursor=0)),
        ("    - item", 4, TextEdit(start=0, end=2, text="", cursor=2)),
        ("    - item", 6, TextEdit(start=0, end=2, text="", cursor=4)),
        (" - item", 3, TextEdit(start=0, end=1, text="", cursor=2)),
        ("- item", 2, None),
        (
            "intro\n   - item",
            11,
            TextEdit(start=6, end=8, text="", cursor=9),
        ),
        ("  - item", 5, None),
    ],
    ids=[
        "column-zero",
        "inside-removed-indentation",
        "on-dash",
        "content-column",
        "one-space",
        "zero-space",
        "later-row-offset",
        "past-content-column",
    ],
)
def test_plan_prompt_bullet_dedent(
    text: str,
    offset: int,
    expected: TextEdit | None,
) -> None:
    assert plan_prompt_bullet_shift(text, offset, dedent=True) == expected


@pytest.mark.parametrize(
    ("lines", "cursor_row", "expected"),
    [
        (["- top-level"], 0, "- "),
        (["- top-level", "  prettier wrapped"], 1, "- "),
        (["- outer", "  - nested"], 1, "  - "),
        (["- outer", "  - nested", "    prettier wrapped"], 2, "  - "),
        (
            ["- outer", "  - nested", "    nested wrapped", "  outer again"],
            3,
            "- ",
        ),
        (["- first", "  first wrapped", "- second", "  second wrapped"], 3, "- "),
    ],
    ids=[
        "top-level-marker",
        "top-level-continuation",
        "nested-marker",
        "nested-continuation",
        "dedented-to-outer",
        "nearest-sibling",
    ],
)
def test_prompt_bullet_sibling_prefix(
    lines: list[str],
    cursor_row: int,
    expected: str,
) -> None:
    assert prompt_bullet_sibling_prefix(lines, cursor_row) == expected


@pytest.mark.parametrize(
    ("lines", "cursor_row"),
    [
        (["ordinary prose"], 0),
        (["- old bullet", "  old continuation", "", "  orphaned text"], 3),
        (
            [
                "- old bullet",
                "  old continuation",
                "dedented paragraph",
                "  orphaned text",
            ],
            3,
        ),
        (["- outer", "  ```python", "  code inside fence"], 2),
        (["- outer", "  ---"], 1),
        (["- outer", "  -tight dash"], 1),
        (["- outer", "  * unsupported child", "    child continuation"], 2),
        (["- outer", "  + unsupported child", "    child continuation"], 2),
        (["- outer", "  1. unsupported child", "    child continuation"], 2),
        (["- outer", "  > quoted text", "    quote continuation"], 2),
        (["- outer", "\ttab continuation"], 1),
        (["\t- tab-indented marker"], 0),
    ],
    ids=[
        "ordinary-prose",
        "blank-boundary",
        "dedented-paragraph",
        "fence-boundary",
        "horizontal-rule",
        "tight-dash",
        "asterisk-marker",
        "plus-marker",
        "ordered-marker",
        "blockquote-marker",
        "tab-continuation",
        "tab-marker",
    ],
)
def test_prompt_bullet_sibling_prefix_rejects_boundaries(
    lines: list[str],
    cursor_row: int,
) -> None:
    assert prompt_bullet_sibling_prefix(lines, cursor_row) is None


@pytest.mark.parametrize(
    ("lines", "cursor_row", "expected"),
    [
        (["- "], 0, False),
        (["", "- "], 1, False),
        (["#gh:sase", "%w:agent text", "", "- "], 3, False),
        (["- item", "- "], 1, True),
        (["- outer", "  - nested", "  - "], 2, True),
        (["- item", "  wrapped", "- "], 2, True),
        (["- item", "", "- "], 2, False),
        (["```", "- "], 1, False),
        (["prose", "- "], 1, False),
    ],
    ids=[
        "first-row",
        "blank-above",
        "reported-prompt-shape",
        "bullet-above",
        "nested-under-sibling",
        "continuation-above",
        "blank-breaks-ownership",
        "fence-above",
        "prose-above",
    ],
)
def test_prompt_bullet_row_has_bullet_above(
    lines: list[str],
    cursor_row: int,
    expected: bool,
) -> None:
    assert prompt_bullet_row_has_bullet_above(lines, cursor_row) is expected


@pytest.mark.parametrize(
    ("structural_line", "replay_text", "expected"),
    [
        ("- ", "- item", "item"),
        ("  - ", "- item", "item"),
        ("  - ", "    - item", "item"),
        ("", "- item", "- item"),
        ("- ", "plain text", "plain text"),
    ],
)
def test_normalize_prompt_bullet_replay_text(
    structural_line: str,
    replay_text: str,
    expected: str,
) -> None:
    assert normalize_prompt_bullet_replay_text(structural_line, replay_text) == expected
