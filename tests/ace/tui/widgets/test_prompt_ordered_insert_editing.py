"""Prompt ordered-list insert-mode (``Ctrl+J``) editing coverage."""

from __future__ import annotations

import os
import shutil

import pytest
from textual.widgets.text_area import Selection

from sase.ace.testing import PromptPage
from sase.file_references import format_agent_prompt_markdown

_requires_prettier = pytest.mark.skipif(
    bool(os.environ.get("SASE_DISABLE_PRETTIER")) or shutil.which("prettier") is None,
    reason="prettier is unavailable or disabled",
)


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        ("1. direct", (0, 5), "1. di\n2. rect", (1, 3)),
        ("1. top\n   wrapped", (1, 6), "1. top\n   wra\n2. pped", (2, 3)),
        (
            "1. outer\n   1. nested",
            (1, 8),
            "1. outer\n   1. ne\n   2. sted",
            (2, 6),
        ),
        (
            "1. outer\n   1. nested\n      wrapped",
            (2, 9),
            "1. outer\n   1. nested\n      wra\n   2. pped",
            (3, 6),
        ),
        ("- hyphen\n1. mixed", (1, 8), "- hyphen\n1. mixed\n2. ", (2, 3)),
    ],
    ids=[
        "direct",
        "wrapped",
        "nested",
        "nested-wrapped",
        "after-hyphen-list",
    ],
)
async def test_prompt_insert_ctrl_j_splits_ordered_item(
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


async def test_prompt_insert_ctrl_j_renumbers_following_ordered_siblings() -> None:
    async with PromptPage("1. one\n2. two", cursor=(0, 6), mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == "1. one\n2. \n3. two"
        assert page.cursor == (1, 3)


async def test_prompt_insert_ctrl_j_renumbers_across_blank_lines() -> None:
    async with PromptPage("1. one\n\n2. two", cursor=(0, 6), mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == "1. one\n2. \n\n3. two"
        assert page.cursor == (1, 3)


async def test_prompt_insert_ctrl_j_preserves_repeat_style() -> None:
    text = "1. a\n1. b\n1. c"
    async with PromptPage(text, cursor=(0, 4), mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == "1. a\n1. \n1. b\n1. c"
        assert page.cursor == (1, 3)


async def test_prompt_insert_ctrl_j_preserves_paren_delimiter() -> None:
    async with PromptPage("1) a\n2) b", cursor=(0, 4), mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == "1) a\n2) \n3) b"
        assert page.cursor == (1, 3)


async def test_prompt_insert_ctrl_j_cursor_survives_width_change_above() -> None:
    # Renumbering ``10. b`` down to ``9. b`` narrows a line *above* the new
    # item, so the cursor offset has to come from the rebuilt text.
    async with PromptPage("8. a\n10. b", cursor=(1, 5), mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == "8. a\n9. b\n10. "
        assert page.cursor == (2, 4)


async def test_prompt_insert_ctrl_j_shifts_owned_block_on_width_change() -> None:
    # ``9. b`` widens to ``10. b``, so the continuation line it owns gains the
    # same one-space delta and stays owned by the item.
    text = "9. a\n9. b\n   cont\n9. d"
    async with PromptPage(text, cursor=(3, 4), mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == "9. a\n10. b\n    cont\n11. d\n12. "
        assert page.cursor == (4, 4)


@pytest.mark.parametrize(
    ("cursor", "expected_text", "expected_cursor"),
    [
        ((1, 1), "1. first\n2\n3. . tail", (2, 3)),
        ((1, 4), "1. first\n2. t\n3. ail", (2, 3)),
    ],
    ids=["inside-marker", "inside-content"],
)
async def test_prompt_insert_ctrl_j_delist_requires_exact_content_column(
    cursor: tuple[int, int],
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    text = "1. first\n2. tail"
    async with PromptPage(text, cursor=cursor, mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == expected_text
        assert page.cursor == expected_cursor


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        ("1. one\n2. #plan", (1, 3), "1. one\n\n#plan", (2, 0)),
        (
            "1. outer\n   1. nested\n   2. #plan",
            (2, 6),
            "1. outer\n   1. nested\n\n#plan",
            (3, 0),
        ),
        ("1. a\n2. #plan\n3. c", (1, 3), "1. a\n\n#plan\n3. c", (2, 0)),
    ],
    ids=["top-level", "nested", "trailing-items-start-a-new-list"],
)
async def test_prompt_insert_ctrl_j_delists_at_content_column(
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


async def test_prompt_insert_ctrl_j_delist_is_one_undo_checkpoint() -> None:
    text = "1. one\n2. #plan"
    async with PromptPage(text, cursor=(1, 3), mode="insert") as page:
        await page.press("ctrl+j")
        assert page.text == "1. one\n\n#plan"

        await page.press("escape", "u")
        assert page.text == text


async def test_prompt_insert_ctrl_j_populated_lone_item_opens_sibling() -> None:
    async with PromptPage("1. #plan", cursor=(0, 3), mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == "1. \n2. #plan"
        assert page.cursor == (1, 3)


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        ("1. ", (0, 3), "1. \n2. ", (1, 3)),
        ("intro\n\n1. ", (2, 3), "intro\n\n1. \n2. ", (3, 3)),
        ("   1. ", (0, 6), "   1. \n   2. ", (1, 6)),
        ("1. ", (0, 0), "1. \n2. ", (1, 3)),
        ("1) ", (0, 3), "1) \n2) ", (1, 3)),
    ],
    ids=[
        "lone",
        "blank-line-above",
        "nested-lone",
        "cursor-inside-marker",
        "paren-delimiter",
    ],
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
        ("1. a\n2. ", (1, 3), "1. a\n\n", (2, 0)),
        ("1. a\n2. b\n3. \n4. d", (2, 3), "1. a\n2. b\n\n\n3. d", (3, 0)),
    ],
    ids=["last-item", "renumbers-items-below-the-hole"],
)
async def test_prompt_insert_ctrl_j_marker_only_line_exits_list(
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
    ("text", "cursor", "expected_text", "expected_cursor", "marker_text"),
    [
        ("1. item", (0, 7), "1. item\n\n", (2, 0), "1. item\n2. "),
        (
            "1. outer\n   1. nested",
            (1, 12),
            "1. outer\n   1. nested\n\n",
            (3, 0),
            "1. outer\n   1. nested\n   2. ",
        ),
    ],
    ids=["top-level", "nested"],
)
async def test_prompt_insert_ctrl_j_twice_exits_item_and_undoes_separately(
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

        await page.press("escape", "u")
        assert page.text == marker_text

        await page.press("u")
        assert page.text == text


async def test_prompt_insert_ctrl_j_twice_exits_from_lone_marker() -> None:
    async with PromptPage("1. ", cursor=(0, 3), mode="insert") as page:
        await page.press("ctrl+j", "ctrl+j")

        assert page.text == "1. \n\n"
        assert page.cursor == (2, 0)

        await page.press("escape", "u")
        assert page.text == "1. \n2. "

        await page.press("u")
        assert page.text == "1. "


async def test_prompt_insert_ctrl_j_undoes_split_and_renumber_together() -> None:
    text = "1. one\n2. two\n3. three"
    async with PromptPage(text, cursor=(0, 6), mode="insert") as page:
        await page.press("ctrl+j")
        assert page.text == "1. one\n2. \n3. two\n4. three"

        await page.press("escape", "u")
        assert page.text == text


async def test_prompt_insert_ctrl_j_prefix_is_its_own_undo_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = 0.0

    def current_time() -> float:
        return clock

    async with PromptPage("1. item", cursor=(0, 7), mode="insert") as page:
        monkeypatch.setattr(page.ta.history, "_get_time", current_time)
        await page.press("ctrl+j")
        for key in ("n", "e", "w"):
            clock += 3.0
            await page.press(key)
        await page.press("escape")
        assert page.text == "1. item\n2. new"

        await page.press("u")
        assert page.text == "1. item\n2. "

        await page.press("u")
        assert page.text == "1. item"


async def test_prompt_insert_ctrl_j_selection_uses_cursor_row() -> None:
    async with PromptPage("1. one\n2. two", mode="insert") as page:
        page.ta.selection = Selection((0, 4), (1, 5))
        await page.press("ctrl+j")

        assert page.text == "1. o\n2. o"
        assert page.cursor == (1, 3)
        assert page.mode == "insert"


async def test_prompt_insert_ctrl_j_marker_selection_uses_replacement_path() -> None:
    async with PromptPage("1. item\n2. ", mode="insert") as page:
        page.ta.selection = Selection((1, 0), (1, 3))
        await page.press("ctrl+j")

        assert page.text == "1. item\n\n2. "
        assert page.cursor == (2, 3)
        assert page.mode == "insert"


async def test_prompt_insert_ctrl_j_populated_selection_uses_replacement_path() -> None:
    async with PromptPage("1. first\n2. #plan", mode="insert") as page:
        page.ta.selection = Selection((1, 0), (1, 3))
        await page.press("ctrl+j")

        assert page.text == "1. first\n\n2. #plan"
        assert page.cursor == (2, 3)


@_requires_prettier
@pytest.mark.parametrize(
    ("text", "cursor", "expected_text"),
    [
        ("1. onetwo\n2. three", (0, 6), "1. one\n2. two\n3. three"),
        ("1. a\n1. bc\n1. d", (1, 4), "1. a\n1. b\n1. c\n1. d"),
        ("1. a\n2. bee", (1, 3), "1. a\n\nbee"),
        ("1. a\n2. bee\n\n3. c", (1, 3), "1. a\n\nbee\n\n3. c"),
    ],
    ids=["split", "repeat-style", "delist", "delist-keeps-later-start"],
)
async def test_prompt_insert_ctrl_j_output_is_a_formatter_fixed_point(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
) -> None:
    """``gf`` right after a ``Ctrl+J`` press must change no numbering."""
    async with PromptPage(text, cursor=cursor, mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == expected_text

    assert format_agent_prompt_markdown(f"{expected_text}\n") == f"{expected_text}\n"


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        ("1. a\n- hyphen", (1, 8), "1. a\n- hyphen\n- ", (2, 2)),
        ("1. a\nplain prose", (1, 11), "1. a\nplain prose\n", (2, 0)),
        ("1234567890. wide", (0, 16), "1234567890. wide\n", (1, 0)),
        ("1.tight", (0, 7), "1.tight\n", (1, 0)),
    ],
    ids=["hyphen-line", "unowned-prose", "too-many-digits", "tight-marker"],
)
async def test_prompt_insert_ctrl_j_leaves_non_ordered_rows_alone(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    async with PromptPage(text, cursor=cursor, mode="insert") as page:
        await page.press("ctrl+j")

        assert page.text == expected_text
        assert page.cursor == expected_cursor
