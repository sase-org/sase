"""Prompt hyphen-bullet insert-mode editing coverage."""

from __future__ import annotations

import pytest
from textual.widgets.text_area import Selection

from sase.ace.testing import PromptPage
from sase.core.snippet_session_facade import (
    SnippetSessionState,
    SnippetSpan,
    SnippetStop,
)


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
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        (
            "- foo bar\n- #plan",
            (1, 2),
            "- foo bar\n\n#plan",
            (2, 0),
        ),
        (
            "- outer\n  - nested\n  - #plan",
            (2, 4),
            "- outer\n  - nested\n\n#plan",
            (3, 0),
        ),
    ],
    ids=["top-level", "nested"],
)
async def test_prompt_insert_ctrl_j_exits_populated_bullet_at_content_column(
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


async def test_prompt_insert_ctrl_j_populated_exit_is_one_undo_checkpoint() -> None:
    text = "- item\n- #plan"
    async with PromptPage(text, cursor=(1, 2), mode="insert") as page:
        await page.press("ctrl+j")
        assert page.text == "- item\n\n#plan"

        await page.press("escape", "u")
        assert page.text == text


async def test_prompt_insert_ctrl_j_populated_lone_bullet_opens_sibling() -> None:
    async with PromptPage("- #plan", cursor=(0, 2), mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == "- \n- #plan"
        assert page.cursor == (1, 2)
        assert page.mode == "insert"


@pytest.mark.parametrize(
    ("cursor", "expected_text", "expected_cursor"),
    [
        ((1, 1), "- first\n-\n-  tail", (2, 2)),
        ((1, 3), "- first\n- t\n- ail", (2, 2)),
    ],
    ids=["before-content-column", "inside-content"],
)
async def test_prompt_insert_ctrl_j_populated_exit_requires_exact_content_column(
    cursor: tuple[int, int],
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    async with PromptPage("- first\n- tail", cursor=cursor, mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == expected_text
        assert page.cursor == expected_cursor
        assert page.mode == "insert"


async def test_prompt_insert_ctrl_j_populated_selection_uses_replacement_path() -> None:
    async with PromptPage("- first\n- #plan", mode="insert") as page:
        page.ta.selection = Selection((1, 0), (1, 2))
        await page.press("ctrl+j")

        assert page.text == "- first\n\n- #plan"
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
        page.ta._snippet_session = SnippetSessionState(
            stops=(SnippetStop(offset=0, session=0), SnippetStop(offset=7, session=0)),
            index=0,
            sessions=(SnippetSpan(id=0, start=0, end=7),),
            next_session_id=1,
        )
        await page.press("tab")

        assert page.text == "- \nnext"
        assert page.cursor == (1, 4)
        assert page.mode == "insert"


async def test_prompt_bullet_indent_remaps_insert_dot_capture() -> None:
    async with PromptPage("- item\nplain", cursor=(0, 2)) as page:
        await page.press("i", "tab", "x", "escape", "j", "0", ".")

        assert page.text == "  - xitem\nxplain"
        assert page.mode == "normal"
