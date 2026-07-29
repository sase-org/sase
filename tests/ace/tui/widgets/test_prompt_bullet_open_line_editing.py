"""Prompt hyphen-bullet normal-mode open-line editing coverage."""

from __future__ import annotations

import pytest

from sase.ace.testing import PromptPage, VimEditorPage


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
