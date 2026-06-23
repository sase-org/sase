"""Tests for PromptTextArea NORMAL-mode Ctrl+A/Ctrl+X number commands."""

from __future__ import annotations

from sase.ace.testing import PromptPage
from sase.ace.tui.widgets._vim_number import compute_number_change


def test_compute_number_change_vectors() -> None:
    """Pure number planning matches the prompt command semantics."""
    cases: list[tuple[str, int, int, tuple[int, int, str, int] | None]] = [
        ("abc", 0, 1, None),
        ("a 9 b", 2, 1, (2, 3, "10", 3)),
        ("a 9 b 10", 3, 1, (6, 8, "11", 7)),
        ("a 1\nb 2", 7, 2, (2, 3, "3", 2)),
        ("-3", 1, -5, (0, 2, "-8", 1)),
        ("009", 0, -10, (0, 3, "-001", 3)),
        ("--5", 0, 1, (1, 3, "-4", 2)),
    ]

    for text, cursor, delta, expected in cases:
        change = compute_number_change(text, cursor, delta)
        actual = (
            None
            if change is None
            else (change.start, change.end, change.new_text, change.new_cursor)
        )
        assert actual == expected


async def test_ctrl_a_increments_number_under_cursor() -> None:
    """Ctrl+A increments the number under the cursor."""
    async with PromptPage("a 9 b", cursor=(0, 2)) as page:
        await page.press("ctrl+a")
        assert page.text == "a 10 b"
        assert page.cursor == (0, 3)


async def test_ctrl_a_targets_next_number_on_same_line() -> None:
    """When not on a number, Ctrl+A targets the next number on the same line."""
    async with PromptPage("a 1 b 2", cursor=(0, 4)) as page:
        await page.press("ctrl+a")
        assert page.text == "a 1 b 3"
        assert page.cursor == (0, 6)


async def test_ctrl_a_targets_number_on_later_line() -> None:
    """When no same-line number is ahead, Ctrl+A searches later lines."""
    async with PromptPage("abc\nvalue 4", cursor=(0, 3)) as page:
        await page.press("ctrl+a")
        assert page.text == "abc\nvalue 5"
        assert page.cursor == (1, 6)


async def test_ctrl_a_wraps_to_first_number() -> None:
    """When no forward number exists, Ctrl+A wraps to the prompt top."""
    async with PromptPage("1 a 2", cursor=(0, 5)) as page:
        await page.press("ctrl+a")
        assert page.text == "2 a 2"
        assert page.cursor == (0, 0)


async def test_ctrl_a_noops_without_numbers() -> None:
    """Ctrl+A is silent when the prompt has no numbers."""
    async with PromptPage("abc", cursor=(0, 1)) as page:
        await page.press("ctrl+a")
        assert page.text == "abc"
        assert page.cursor == (0, 1)


async def test_ctrl_x_decrements_signed_number_with_count() -> None:
    """A count prefix multiplies Ctrl+X's negative delta."""
    async with PromptPage("-3", cursor=(0, 1)) as page:
        await page.press("5", "ctrl+x")
        assert page.text == "-8"
        assert page.cursor == (0, 1)


async def test_ctrl_x_can_cross_zero() -> None:
    """Ctrl+X can turn zero into a negative number."""
    async with PromptPage("0") as page:
        await page.press("ctrl+x")
        assert page.text == "-1"
        assert page.cursor == (0, 1)


async def test_number_commands_preserve_leading_zero_width() -> None:
    """Leading-zero digit width is preserved when the original had padding."""
    async with PromptPage("007") as page:
        await page.press("ctrl+a")
        assert page.text == "008"
        assert page.cursor == (0, 2)

    async with PromptPage("009") as page:
        await page.press("1", "0", "ctrl+x")
        assert page.text == "-001"
        assert page.cursor == (0, 3)

    async with PromptPage("9") as page:
        await page.press("ctrl+a")
        assert page.text == "10"
        assert page.cursor == (0, 1)


async def test_ctrl_a_count_adds_count() -> None:
    """A count prefix multiplies Ctrl+A's positive delta."""
    async with PromptPage("2") as page:
        await page.press("5", "ctrl+a")
        assert page.text == "7"
        assert page.cursor == (0, 0)


async def test_dot_repeats_number_increment() -> None:
    """Dot repeats Ctrl+A on the same number."""
    async with PromptPage("1") as page:
        await page.press("ctrl+a")
        await page.press(".")
        assert page.text == "3"
        assert page.cursor == (0, 0)


async def test_dot_repeats_number_increment_with_count() -> None:
    """Dot repeats Ctrl+A with its recorded count."""
    async with PromptPage("1") as page:
        await page.press("3", "ctrl+a")
        await page.press(".")
        assert page.text == "7"
        assert page.cursor == (0, 0)


async def test_insert_mode_ctrl_a_keeps_readline_behavior() -> None:
    """INSERT-mode Ctrl+A still moves to the start of the line."""
    async with PromptPage("abc 123", cursor=(0, 4), mode="insert") as page:
        await page.press("ctrl+a")
        assert page.text == "abc 123"
        assert page.cursor == (0, 0)
