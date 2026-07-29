"""Prompt hyphen-bullet ownership and open-line editing coverage."""

from __future__ import annotations

import pytest
from textual.widgets.text_area import Selection

from sase.ace.testing import PromptPage, VimEditorPage
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


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        ("- direct", (0, 4), "- di\n- rect", (1, 2)),
        ("- top\n  wrapped", (1, 4), "- top\n  wr\n- apped", (2, 2)),
        ("- outer\n  - nested", (1, 6), "- outer\n  - ne\n  - sted", (2, 4)),
        (
            "- outer\n  - nested\n    wrapped",
            (2, 7),
            "- outer\n  - nested\n    wra\n  - pped",
            (3, 4),
        ),
        ("plain line", (0, 5), "plain\n line", (1, 0)),
    ],
    ids=[
        "direct",
        "wrapped",
        "nested",
        "nested-wrapped",
        "plain",
    ],
)
async def test_prompt_insert_ctrl_j_splits_with_structural_prefix(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    async with PromptPage(text, cursor=cursor, mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == expected_text
        assert page.cursor == expected_cursor
        assert page.mode == "insert"


async def test_prompt_insert_ctrl_j_selection_uses_cursor_row() -> None:
    async with PromptPage("intro\n- bullet tail", mode="insert") as page:
        page.ta.selection = Selection((0, 2), (1, 5))
        await page.press("ctrl+j")

        assert page.text == "in\n- let tail"
        assert page.cursor == (1, 2)
        assert page.mode == "insert"


async def test_prompt_insert_ctrl_j_marker_selection_uses_replacement_path() -> None:
    async with PromptPage("- item\n- ", mode="insert") as page:
        page.ta.selection = Selection((1, 0), (1, 2))
        await page.press("ctrl+j")

        assert page.text == "- item\n\n- "
        assert page.cursor == (2, 2)
        assert page.mode == "insert"


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor", "marker_text"),
    [
        ("- item", (0, 6), "- item\n\n", (2, 0), "- item\n- "),
        (
            "- outer\n  - nested",
            (1, 10),
            "- outer\n  - nested\n\n",
            (3, 0),
            "- outer\n  - nested\n  - ",
        ),
    ],
    ids=["top-level", "nested"],
)
async def test_prompt_insert_ctrl_j_twice_exits_bullet_and_undoes_separately(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_cursor: tuple[int, int],
    marker_text: str,
) -> None:
    async with PromptPage(text, cursor=cursor, mode="insert") as page:
        await page.press("ctrl+j", "ctrl+j")

        assert page.text == expected_text
        assert page.cursor == expected_cursor
        assert page.mode == "insert"

        await page.press("escape", "u")
        assert page.text == marker_text

        await page.press("u")
        assert page.text == text


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        ("- ", (0, 2), "- \n- ", (1, 2)),
        ("intro\n\n- ", (2, 2), "intro\n\n- \n- ", (3, 2)),
        ("  - ", (0, 4), "  - \n  - ", (1, 4)),
        ("- ", (0, 0), "- \n- ", (1, 2)),
    ],
    ids=["lone", "blank-line-above", "nested-lone", "cursor-inside-marker"],
)
async def test_prompt_insert_ctrl_j_lone_marker_opens_sibling(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    async with PromptPage(text, cursor=cursor, mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == expected_text
        assert page.cursor == expected_cursor
        assert page.mode == "insert"


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        ("- ", (0, 2), "- \n\n", (2, 0)),
        ("intro\n\n- ", (2, 2), "intro\n\n- \n\n", (4, 0)),
    ],
    ids=["lone", "blank-line-above"],
)
async def test_prompt_insert_ctrl_j_twice_exits_from_lone_marker(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    async with PromptPage(text, cursor=cursor, mode="insert") as page:
        await page.press("ctrl+j", "ctrl+j")

        assert page.text == expected_text
        assert page.cursor == expected_cursor
        assert page.mode == "insert"


async def test_prompt_insert_ctrl_j_lone_marker_undoes_separately() -> None:
    async with PromptPage("- ", cursor=(0, 2), mode="insert") as page:
        await page.press("ctrl+j", "ctrl+j")
        assert page.text == "- \n\n"

        await page.press("escape", "u")
        assert page.text == "- \n- "

        await page.press("u")
        assert page.text == "- "


async def test_prompt_insert_ctrl_j_prefix_is_its_own_undo_checkpoint() -> None:
    async with PromptPage("- item", cursor=(0, 6), mode="insert") as page:
        await page.press("ctrl+j", "n", "e", "w", "escape")
        assert page.text == "- item\n- new"

        await page.press("u")
        assert page.text == "- item\n- "

        await page.press("u")
        assert page.text == "- item"


async def test_prompt_insert_tab_indents_and_shift_tab_dedents_marker() -> None:
    async with PromptPage("- ", cursor=(0, 2), mode="insert") as page:
        await page.press("tab")
        assert page.text == "  - "
        assert page.cursor == (0, 4)
        assert page.mode == "insert"

        await page.press("shift+tab")
        assert page.text == "- "
        assert page.cursor == (0, 2)
        assert page.mode == "insert"


async def test_prompt_insert_repeated_tabs_accumulate_bullet_indent() -> None:
    async with PromptPage("- item", cursor=(0, 2), mode="insert") as page:
        await page.press("tab", "tab")

        assert page.text == "    - item"
        assert page.cursor == (0, 6)
        assert page.mode == "insert"


async def test_prompt_insert_shift_tab_dedents_one_unit() -> None:
    async with PromptPage("      - item", cursor=(0, 8), mode="insert") as page:
        await page.press("shift+tab")

        assert page.text == "    - item"
        assert page.cursor == (0, 6)
        assert page.mode == "insert"


@pytest.mark.parametrize(
    ("text", "cursor"),
    [
        ("- item", (0, 2)),
        ("plain prose", (0, 0)),
    ],
    ids=["unindented-bullet", "prose"],
)
async def test_prompt_insert_shift_tab_noop(
    text: str,
    cursor: tuple[int, int],
) -> None:
    async with PromptPage(text, cursor=cursor, mode="insert") as page:
        await page.press("shift+tab")

        assert page.text == text
        assert page.cursor == cursor
        assert page.mode == "insert"


async def test_prompt_insert_tab_does_not_indent_active_selection() -> None:
    async with PromptPage("- item", mode="insert") as page:
        page.ta.selection = Selection((0, 0), (0, 2))
        await page.press("tab")

        assert page.text == "- item"
        assert page.ta.selection == Selection((0, 0), (0, 2))
        assert page.mode == "insert"


async def test_prompt_insert_tab_indent_is_one_undo_checkpoint() -> None:
    async with PromptPage("- item", cursor=(0, 2), mode="insert") as page:
        await page.press("tab", "escape", "u")

        assert page.text == "- item"
        assert page.mode == "normal"


async def test_prompt_insert_tab_advances_queued_tabstop_before_bullet_indent() -> None:
    async with PromptPage("- \nnext", cursor=(0, 2), mode="insert") as page:
        page.ta._snippet_tabstops = [0]
        page.ta._snippet_end_from_doc_end = 0
        await page.press("tab")

        assert page.text == "- \nnext"
        assert page.cursor == (1, 4)
        assert page.mode == "insert"


async def test_prompt_bullet_indent_remaps_insert_dot_capture() -> None:
    async with PromptPage("- item\nplain", cursor=(0, 2)) as page:
        await page.press("i", "tab", "x", "escape", "j", "0", ".")

        assert page.text == "  - xitem\nxplain"
        assert page.mode == "normal"


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        ("- direct", (0, 3), "- direct\n- ", (1, 2)),
        ("- direct\n  wrapped", (1, 4), "- direct\n  wrapped\n- ", (2, 2)),
        ("- outer\n  - nested", (1, 5), "- outer\n  - nested\n  - ", (2, 4)),
        (
            "- outer\n  - nested\n    wrapped",
            (2, 6),
            "- outer\n  - nested\n    wrapped\n  - ",
            (3, 4),
        ),
        ("plain line", (0, 2), "plain line\n", (1, 0)),
    ],
    ids=[
        "direct",
        "wrapped",
        "nested",
        "nested-wrapped",
        "plain",
    ],
)
async def test_prompt_normal_o_inserts_structural_prefix(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    async with PromptPage(text, cursor=cursor) as page:
        await page.press("o")

        assert page.text == expected_text
        assert page.cursor == expected_cursor
        assert page.mode == "insert"


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        ("- direct", (0, 3), "- \n- direct", (0, 2)),
        ("- direct\n  wrapped", (1, 4), "- direct\n- \n  wrapped", (1, 2)),
        ("- outer\n  - nested", (1, 5), "- outer\n  - \n  - nested", (1, 4)),
        (
            "- outer\n  - nested\n    wrapped",
            (2, 6),
            "- outer\n  - nested\n  - \n    wrapped",
            (2, 4),
        ),
        ("plain line", (0, 2), "\nplain line", (0, 0)),
    ],
    ids=[
        "direct",
        "wrapped",
        "nested",
        "nested-wrapped",
        "plain",
    ],
)
async def test_prompt_normal_upper_o_inserts_structural_prefix(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    async with PromptPage(text, cursor=cursor) as page:
        await page.press("O")

        assert page.text == expected_text
        assert page.cursor == expected_cursor
        assert page.mode == "insert"


@pytest.mark.parametrize(
    ("key", "expected_text", "expected_cursor"),
    [
        ("o", "- item\n", (1, 0)),
        ("O", "\n- item", (0, 0)),
    ],
    ids=["below", "above"],
)
async def test_bare_vim_text_area_normal_open_line_remains_bare(
    key: str,
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    async with VimEditorPage("- item", cursor=(0, 2)) as page:
        await page.press(key)

        assert page.text == expected_text
        assert page.cursor == expected_cursor
        assert page.mode == "insert"


async def test_prompt_bullet_o_undo_keeps_existing_insert_checkpoints() -> None:
    async with PromptPage("- item", cursor=(0, 2)) as page:
        await page.press("o", "n", "e", "w", "escape")
        assert page.text == "- item\n- new"

        await page.press("u")
        assert page.text == "- item\n- "

        await page.press("u")
        assert page.text == "- item"


async def test_prompt_bullet_upper_o_undo_keeps_structural_marker() -> None:
    async with PromptPage("- item", cursor=(0, 2)) as page:
        await page.press("O", "n", "e", "w", "escape")
        assert page.text == "- new\n- item"

        await page.press("u")
        assert page.text == "- \n- item"

        await page.press("u")
        assert page.text == "- item"


async def test_prompt_bullet_o_dot_repeat_rechecks_destination_context() -> None:
    async with PromptPage(
        "- outer\n  - nested\n    wrapped",
        cursor=(0, 2),
    ) as page:
        await page.press("o", "n", "e", "w", "escape")
        await page.press("2", "j", ".")

        assert page.text == ("- outer\n- new\n  - nested\n    wrapped\n  - new")
        assert page.text.count("  - new") == 1
        assert page.mode == "normal"


async def test_prompt_bullet_upper_o_dot_repeat_does_not_leak_marker_to_prose() -> None:
    async with PromptPage("- item\nplain", cursor=(0, 2)) as page:
        await page.press("O", "n", "e", "w", "escape")
        await page.press("2", "j", ".")

        assert page.text == "- new\n- item\nnew\nplain"
        assert page.mode == "normal"


async def test_prompt_bullet_upper_o_dot_repeat_avoids_duplicate_nested_marker() -> (
    None
):
    async with PromptPage(
        "plain\n- outer\n  - nested\n    wrapped",
        cursor=(0, 2),
    ) as page:
        await page.press("O", "-", "space", "n", "e", "w", "escape")
        await page.press("4", "j", ".")

        assert page.text == ("- new\nplain\n- outer\n  - nested\n  - new\n    wrapped")
        assert page.text.count("  - new") == 1
        assert page.mode == "normal"
