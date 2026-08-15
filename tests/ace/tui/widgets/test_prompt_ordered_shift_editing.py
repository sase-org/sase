"""Prompt ordered-item INSERT-mode ``Tab`` / ``Shift+Tab`` nesting coverage."""

from __future__ import annotations

import os
import shutil

import pytest
from textual.widgets.text_area import Selection

from sase.ace.testing import PromptPage
from sase.ace.tui.widgets._prompt_ordered_shift_editing import (
    plan_prompt_ordered_shift,
)
from sase.core.snippet_session_facade import (
    SnippetSessionState,
    _SnippetSpan,
    _SnippetStop,
)
from sase.file_references import format_agent_prompt_markdown


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        (
            "1. one\n2. two\n3. three",
            (1, 3),
            "1. one\n   1. two\n2. three",
            (1, 6),
        ),
        (
            "1. one\n2. two\n3. three",
            (1, 5),
            "1. one\n   1. two\n2. three",
            (1, 8),
        ),
        (
            "- parent\n1. item",
            (1, 3),
            "- parent\n  1. item",
            (1, 5),
        ),
        (
            "1. outer\n   1. child\n2. moved",
            (2, 3),
            "1. outer\n   1. child\n   2. moved",
            (2, 6),
        ),
        (
            "1) one\n2) two\n3) three",
            (1, 3),
            "1) one\n   1) two\n2) three",
            (1, 6),
        ),
        (
            "1. one\n1. two\n1. three",
            (1, 3),
            "1. one\n   1. two\n1. three",
            (1, 6),
        ),
    ],
    ids=[
        "ordered-parent",
        "ordered-parent-inside-content",
        "hyphen-parent",
        "continues-nested-run",
        "paren-delimiter",
        "repeat-style-preserved",
    ],
)
async def test_prompt_insert_tab_nests_ordered_item(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    async with PromptPage(text, cursor=cursor, mode="insert") as page:
        await page.press("tab")

        assert page.text == expected_text
        assert page.cursor == expected_cursor
        assert page.mode == "insert"


async def test_prompt_insert_tab_moves_owned_block_and_closes_source_gap() -> None:
    text = "1. one\n2. two\n   continuation\n3. three"
    async with PromptPage(text, cursor=(1, 5), mode="insert") as page:
        await page.press("tab")

        assert page.text == ("1. one\n   1. two\n      continuation\n2. three")
        assert page.cursor == (1, 8)


async def test_prompt_insert_tab_nests_from_column_zero() -> None:
    async with PromptPage("1. one\n2. two", cursor=(1, 0), mode="insert") as page:
        await page.press("tab")

        assert page.text == "1. one\n   1. two"
        assert page.cursor == (1, 3)


@pytest.mark.parametrize(
    ("text", "cursor", "expected_text", "expected_cursor"),
    [
        (
            "1. one\n   1. inner\n2. two",
            (1, 6),
            "1. one\n2. inner\n3. two",
            (1, 3),
        ),
        (
            "1. one\n   1. inner\n2. two",
            (1, 9),
            "1. one\n2. inner\n3. two",
            (1, 6),
        ),
        (
            "- parent\n  1. inner",
            (1, 5),
            "- parent\n1. inner",
            (1, 3),
        ),
        (
            "1. outer\n   1. first\n   2. second",
            (2, 6),
            "1. outer\n   1. first\n2. second",
            (2, 3),
        ),
    ],
    ids=[
        "into-outer-run",
        "into-outer-run-inside-content",
        "hyphen-parent",
        "trailing-nested-item",
    ],
)
async def test_prompt_insert_shift_tab_unnests_ordered_item(
    text: str,
    cursor: tuple[int, int],
    expected_text: str,
    expected_cursor: tuple[int, int],
) -> None:
    async with PromptPage(text, cursor=cursor, mode="insert") as page:
        await page.press("shift+tab")

        assert page.text == expected_text
        assert page.cursor == expected_cursor
        assert page.mode == "insert"


async def test_prompt_insert_shift_tab_unnest_moves_owned_block() -> None:
    text = "1. outer\n   1. inner\n      wrapped\n   2. after"
    async with PromptPage(text, cursor=(1, 9), mode="insert") as page:
        await page.press("shift+tab")

        assert page.text == ("1. outer\n2. inner\n   wrapped\n   2. after")
        assert page.cursor == (1, 6)


async def test_prompt_insert_shift_tab_unnest_renumbers_width_from_content() -> None:
    text = "8. outer\n   1. inner\n9. after"
    async with PromptPage(text, cursor=(1, 11), mode="insert") as page:
        await page.press("shift+tab")

        assert page.text == "8. outer\n9. inner\n10. after"
        assert page.cursor == (1, 8)


async def test_prompt_insert_tab_renumbers_source_run_across_blank_lines() -> None:
    text = "1. one\n\n2. two\n\n3. three"
    async with PromptPage(text, cursor=(2, 3), mode="insert") as page:
        await page.press("tab")

        assert page.text == "1. one\n\n   1. two\n\n2. three"


@pytest.mark.parametrize(
    ("text", "cursor", "key"),
    [
        ("1. only", (0, 3), "tab"),
        ("intro\n1. first", (1, 3), "tab"),
        ("1. one\n2. two", (1, 3), "shift+tab"),
    ],
    ids=[
        "tab-without-parent",
        "tab-after-prose",
        "shift-tab-outermost",
    ],
)
async def test_prompt_insert_ordered_shift_noop(
    text: str,
    cursor: tuple[int, int],
    key: str,
) -> None:
    async with PromptPage(text, cursor=cursor, mode="insert") as page:
        await page.press(key)

        assert page.text == text
        assert page.cursor == cursor
        assert page.mode == "insert"


async def test_prompt_insert_ordered_nest_is_one_undo_checkpoint() -> None:
    text = "1. one\n2. two\n3. three"
    async with PromptPage(text, cursor=(1, 3), mode="insert") as page:
        await page.press("tab")
        assert page.text == "1. one\n   1. two\n2. three"

        await page.press("escape", "u")
        assert page.text == text


async def test_prompt_insert_ordered_unnest_is_one_undo_checkpoint() -> None:
    text = "1. one\n   1. inner\n2. two"
    async with PromptPage(text, cursor=(1, 6), mode="insert") as page:
        await page.press("shift+tab")
        assert page.text == "1. one\n2. inner\n3. two"

        await page.press("escape", "u")
        assert page.text == text


async def test_prompt_insert_tab_does_not_nest_active_selection() -> None:
    text = "1. one\n2. two"
    async with PromptPage(text, mode="insert") as page:
        page.ta.selection = Selection((1, 0), (1, 3))
        await page.press("tab")

        assert page.text == text
        assert page.ta.selection == Selection((1, 0), (1, 3))


async def test_prompt_insert_tab_advances_queued_tabstop_before_ordered_nest() -> None:
    text = "1. one\n2. \nnext"
    async with PromptPage(text, cursor=(1, 3), mode="insert") as page:
        page.ta._snippet_session = SnippetSessionState(
            stops=(
                _SnippetStop(offset=0, session=0),
                _SnippetStop(offset=15, session=0),
            ),
            index=0,
            sessions=(_SnippetSpan(id=0, start=0, end=15),),
            next_session_id=1,
        )
        await page.press("tab")

        assert page.text == text
        assert page.cursor == (2, 4)
        assert page.mode == "insert"


async def test_prompt_ordered_nest_remaps_insert_dot_capture() -> None:
    async with PromptPage("- p\n1. item\nplain", cursor=(1, 3)) as page:
        await page.press("i", "tab", "x", "escape", "j", "0", ".")

        assert page.text == "- p\n  1. xitem\nxplain"
        assert page.mode == "normal"


def test_plan_prompt_ordered_shift_declines_hyphen_marker() -> None:
    assert plan_prompt_ordered_shift("- outer\n- item", 10, dedent=False) is None


@pytest.mark.parametrize(
    ("text", "offset", "dedent"),
    [
        ("1. one\n2. two\n3. three", 10, False),
        ("- parent\n1. item", 12, False),
        ("1. outer\n   1. child\n2. moved", 24, False),
        ("1. one\n   1. inner\n2. two", 13, True),
        ("1. outer\n   1. first\n   2. second", 27, True),
    ],
    ids=[
        "nest-under-ordered",
        "nest-under-hyphen",
        "continue-nested-run",
        "unnest-into-outer-run",
        "unnest-trailing-item",
    ],
)
@pytest.mark.skipif(
    bool(os.environ.get("SASE_DISABLE_PRETTIER")) or shutil.which("prettier") is None,
    reason="prettier is unavailable or disabled",
)
def test_nested_result_is_a_formatter_fixed_point(
    text: str,
    offset: int,
    dedent: bool,
) -> None:
    """What a nest or unnest produces survives ``gf`` unchanged."""
    plan = plan_prompt_ordered_shift(text, offset, dedent=dedent)

    assert plan is not None
    shifted = text[: plan.start] + plan.text + text[plan.end :]
    assert format_agent_prompt_markdown(f"{shifted}\n") == f"{shifted}\n"


@pytest.mark.parametrize(
    ("text", "offset", "dedent", "expected_text", "expected_cursor"),
    [
        (
            "1. one\n2. two",
            12,
            False,
            "1. one\n   1. two",
            15,
        ),
        (
            "1. one\n   1. inner\n2. two",
            16,
            True,
            "1. one\n2. inner\n3. two",
            13,
        ),
    ],
    ids=["tab-inside-content", "shift-tab-inside-content"],
)
def test_plan_prompt_ordered_shift_plans_from_item_content(
    text: str,
    offset: int,
    dedent: bool,
    expected_text: str,
    expected_cursor: int,
) -> None:
    plan = plan_prompt_ordered_shift(text, offset, dedent=dedent)

    assert plan is not None
    assert text[: plan.start] + plan.text + text[plan.end :] == expected_text
    assert plan.cursor == expected_cursor


@pytest.mark.parametrize("offset", [-1, 100])
def test_plan_prompt_ordered_shift_rejects_out_of_range_offsets(offset: int) -> None:
    assert plan_prompt_ordered_shift("1. one\n2. two", offset, dedent=False) is None


def test_plan_prompt_ordered_shift_plans_one_edit_for_later_row() -> None:
    text = "1. one\n2. two\n3. three"
    plan = plan_prompt_ordered_shift(text, 10, dedent=False)

    assert plan is not None
    assert text[: plan.start] + plan.text + text[plan.end :] == (
        "1. one\n   1. two\n2. three"
    )
    # The edit spans only the rows the nest actually changed.
    assert text[plan.start : plan.end] == "2. two\n3. three"
