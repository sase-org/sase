"""Prompt hyphen-bullet ownership and NORMAL-mode ``o`` coverage."""

from __future__ import annotations

import pytest

from sase.ace.testing import PromptPage, VimEditorPage
from sase.ace.tui.widgets._prompt_bullet_editing import (
    normalize_prompt_bullet_replay_text,
    prompt_bullet_sibling_prefix,
)


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


async def test_prompt_normal_upper_o_remains_bare_open_above() -> None:
    async with PromptPage("- item", cursor=(0, 2)) as page:
        await page.press("O")

        assert page.text == "\n- item"
        assert page.cursor == (0, 0)
        assert page.mode == "insert"


async def test_bare_vim_text_area_normal_o_remains_bare_open_below() -> None:
    async with VimEditorPage("- item", cursor=(0, 2)) as page:
        await page.press("o")

        assert page.text == "- item\n"
        assert page.cursor == (1, 0)
        assert page.mode == "insert"


async def test_prompt_bullet_o_undo_keeps_existing_insert_checkpoints() -> None:
    async with PromptPage("- item", cursor=(0, 2)) as page:
        await page.press("o", "n", "e", "w", "escape")
        assert page.text == "- item\n- new"

        await page.press("u")
        assert page.text == "- item\n- "

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
