"""Prompt ordered-list normal-mode open-line (``o`` / ``O``) editing coverage."""

from __future__ import annotations

import os
import shutil

import pytest

from sase.ace.testing import PromptPage, VimEditorPage
from sase.file_references import format_agent_prompt_markdown

_requires_prettier = pytest.mark.skipif(
    bool(os.environ.get("SASE_DISABLE_PRETTIER")) or shutil.which("prettier") is None,
    reason="prettier is unavailable or disabled",
)


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        ("1. direct", (0, 5), "1. direct\n2. ", (1, 3)),
        ("1. top\n   wrapped", (1, 4), "1. top\n   wrapped\n2. ", (2, 3)),
        (
            "1. outer\n   1. nested",
            (1, 8),
            "1. outer\n   1. nested\n   2. ",
            (2, 6),
        ),
        (
            "1. outer\n   1. nested\n      wrapped",
            (2, 9),
            "1. outer\n   1. nested\n      wrapped\n   2. ",
            (3, 6),
        ),
        ("1) direct", (0, 5), "1) direct\n2) ", (1, 3)),
        ("- hyphen", (0, 5), "- hyphen\n- ", (1, 2)),
        ("plain line", (0, 2), "plain line\n", (1, 0)),
    ],
    ids=[
        "direct",
        "wrapped",
        "nested",
        "nested-wrapped",
        "paren-delimiter",
        "hyphen-untouched",
        "plain",
    ],
)
async def test_prompt_normal_o_opens_numbered_ordered_sibling(
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
        ("1. direct", (0, 5), "1. \n2. direct", (0, 3)),
        ("1. top\n   wrapped", (1, 4), "1. top\n2. \n   wrapped", (1, 3)),
        (
            "1. outer\n   1. nested",
            (1, 8),
            "1. outer\n   1. \n   2. nested",
            (1, 6),
        ),
        (
            "1. outer\n   1. nested\n      wrapped",
            (2, 9),
            "1. outer\n   1. nested\n   2. \n      wrapped",
            (2, 6),
        ),
        ("1) direct", (0, 5), "1) \n2) direct", (0, 3)),
        ("- hyphen", (0, 5), "- \n- hyphen", (0, 2)),
        ("plain line", (0, 2), "\nplain line", (0, 0)),
    ],
    ids=[
        "direct",
        "wrapped",
        "nested",
        "nested-wrapped",
        "paren-delimiter",
        "hyphen-untouched",
        "plain",
    ],
)
async def test_prompt_normal_upper_o_opens_numbered_ordered_sibling(
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
    ("key", "text", "cursor", "expected_text", "expected_cursor"),
    [
        ("o", "1. one\n2. two", (0, 6), "1. one\n2. \n3. two", (1, 3)),
        ("O", "1. one\n2. two", (1, 6), "1. one\n2. \n3. two", (1, 3)),
        ("o", "1. one\n\n2. two", (0, 6), "1. one\n2. \n\n3. two", (1, 3)),
        ("o", "1. a\n1. b\n1. c", (0, 4), "1. a\n1. \n1. b\n1. c", (1, 3)),
        ("O", "1. a\n1. b\n1. c", (1, 4), "1. a\n1. \n1. b\n1. c", (1, 3)),
        ("o", "1) one\n2) two", (0, 6), "1) one\n2) \n3) two", (1, 3)),
    ],
    ids=[
        "below-renumbers-siblings",
        "above-renumbers-siblings",
        "renumbers-across-blank-lines",
        "below-preserves-repeat-style",
        "above-preserves-repeat-style",
        "preserves-paren-delimiter",
    ],
)
async def test_prompt_normal_open_line_renumbers_the_run(
    key: str,
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    async with PromptPage(text, cursor=cursor) as page:
        await page.press(key)

        assert page.text == expected_text
        assert page.cursor == expected_cursor


async def test_prompt_normal_o_shifts_owned_lines_on_marker_width_growth() -> None:
    async with PromptPage("8. eight\n9. nine\n   wrapped", cursor=(0, 8)) as page:
        await page.press("o")

        assert page.text == "8. eight\n9. \n10. nine\n    wrapped"
        assert page.cursor == (1, 3)


async def test_prompt_normal_o_cursor_survives_narrowing_lines_above_it() -> None:
    async with PromptPage("1. a\n10. b\n11. c", cursor=(2, 5)) as page:
        await page.press("o")

        assert page.text == "1. a\n2. b\n3. c\n4. "
        assert page.cursor == (3, 3)


async def test_prompt_normal_o_leaves_a_run_that_is_too_large_unrenumbered() -> None:
    from sase.ace.tui.widgets._prompt_ordered_editing import MAX_ORDERED_RUN_ITEMS

    items = [f"{index + 1}. item" for index in range(MAX_ORDERED_RUN_ITEMS + 2)]
    async with PromptPage("\n".join(items), cursor=(0, 7)) as page:
        await page.press("o")

        lines = page.text.split("\n")
        assert lines[1] == "2. "
        # The structural edit still happened; the numbering below it did not
        # move, because the run exceeds the per-keystroke cap.
        assert lines[2] == "2. item"


async def test_prompt_normal_o_undo_reverts_insertion_and_renumbering_together() -> (
    None
):
    async with PromptPage("1. one\n2. two", cursor=(0, 6)) as page:
        await page.press("o", "n", "e", "w", "escape")
        assert page.text == "1. one\n2. new\n3. two"

        await page.press("u")
        assert page.text == "1. one\n2. \n3. two"

        await page.press("u")
        assert page.text == "1. one\n2. two"


async def test_prompt_normal_upper_o_undo_reverts_insertion_and_renumbering() -> None:
    async with PromptPage("1. one\n2. two", cursor=(1, 6)) as page:
        await page.press("O", "n", "e", "w", "escape")
        assert page.text == "1. one\n2. new\n3. two"

        await page.press("u")
        assert page.text == "1. one\n2. \n3. two"

        await page.press("u")
        assert page.text == "1. one\n2. two"


async def test_prompt_ordered_o_dot_repeat_rechecks_destination_context() -> None:
    async with PromptPage(
        "1. outer\n   1. nested\n      wrapped",
        cursor=(0, 3),
    ) as page:
        await page.press("o", "n", "e", "w", "escape")
        assert page.text == "1. outer\n2. new\n   1. nested\n      wrapped"

        await page.press("2", "j", ".")

        assert page.text == ("1. outer\n2. new\n   1. nested\n      wrapped\n   2. new")
        assert page.text.count("   2. new") == 1
        assert page.mode == "normal"


async def test_prompt_ordered_upper_o_dot_repeat_does_not_leak_marker_to_prose() -> (
    None
):
    async with PromptPage("1. item\nplain", cursor=(0, 3)) as page:
        await page.press("O", "n", "e", "w", "escape")
        assert page.text == "1. new\n2. item\nplain"

        await page.press("2", "j", ".")

        assert page.text == "1. new\n2. item\nnew\nplain"
        assert page.mode == "normal"


async def test_prompt_ordered_upper_o_dot_repeat_avoids_duplicate_marker() -> None:
    async with PromptPage(
        "plain\n1. outer\n   1. nested\n      wrapped",
        cursor=(0, 2),
    ) as page:
        await page.press("O", "1", "full_stop", "space", "n", "e", "w", "escape")
        assert page.text == "1. new\nplain\n1. outer\n   1. nested\n      wrapped"

        await page.press("4", "j", ".")

        assert page.text == (
            "1. new\nplain\n1. outer\n   1. nested\n   2. new\n      wrapped"
        )
        assert page.text.count("   2. new") == 1
        assert page.mode == "normal"


@pytest.mark.parametrize(
    ("key", "expected_text", "expected_cursor"),
    [
        ("o", "1. item\n", (1, 0)),
        ("O", "\n1. item", (0, 0)),
    ],
    ids=["below", "above"],
)
async def test_bare_vim_text_area_ordered_open_line_remains_bare(
    key: str,
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    async with VimEditorPage("1. item", cursor=(0, 3)) as page:
        await page.press(key)

        assert page.text == expected_text
        assert page.cursor == expected_cursor
        assert page.mode == "insert"


@_requires_prettier
@pytest.mark.parametrize(
    ("key", "text", "cursor", "typed", "expected_text"),
    [
        ("o", "1. one\n2. three", (0, 6), "two", "1. one\n2. two\n3. three"),
        ("O", "1. one\n3. three", (1, 8), "two", "1. one\n2. two\n3. three"),
        ("o", "1. a\n1. c", (0, 4), "b", "1. a\n1. b\n1. c"),
    ],
    ids=["below", "above", "repeat-style"],
)
async def test_prompt_normal_open_line_output_is_a_formatter_fixed_point(
    key: str,
    text: str,
    cursor: tuple[int, int],
    typed: str,
    expected_text: str,
) -> None:
    """``gf`` right after an ``o`` / ``O`` press must change no numbering."""
    async with PromptPage(text, cursor=cursor) as page:
        await page.press(key, *typed, "escape")

        assert page.text == expected_text

    assert format_agent_prompt_markdown(f"{expected_text}\n") == f"{expected_text}\n"
