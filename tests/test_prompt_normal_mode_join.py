"""Tests for PromptTextArea NORMAL-mode J (join lines) command."""

from sase.ace.testing import PromptPage


# =============================================================================
# Basic join tests
# =============================================================================


async def test_join_two_lines() -> None:
    """J joins the current line with the next, inserting a space."""
    async with PromptPage("hello\nworld") as page:
        await page.press("J")
        assert page.text == "hello world"
        assert page.cursor == (0, 5)


async def test_join_strips_leading_whitespace() -> None:
    """J strips leading whitespace from the joined line."""
    async with PromptPage("hello\n    world") as page:
        await page.press("J")
        assert page.text == "hello world"
        assert page.cursor == (0, 5)


async def test_join_strips_trailing_whitespace() -> None:
    """J strips trailing whitespace from the current line."""
    async with PromptPage("hello   \nworld") as page:
        await page.press("J")
        assert page.text == "hello world"
        assert page.cursor == (0, 5)


async def test_join_on_last_line_is_noop() -> None:
    """J on the last line does nothing."""
    async with PromptPage("only line") as page:
        await page.press("J")
        assert page.text == "only line"


async def test_join_empty_next_line() -> None:
    """J with an empty next line just removes the newline."""
    async with PromptPage("hello\n\nworld") as page:
        await page.press("J")
        assert page.text == "hello\nworld"


# =============================================================================
# Prompt hyphen bullets
# =============================================================================


async def test_join_strips_prompt_bullet_marker() -> None:
    """J drops the marker from a prompt bullet folded into another bullet."""
    async with PromptPage("- one\n- two") as page:
        await page.press("J")
        assert page.text == "- one two"
        assert page.cursor == (0, 5)


async def test_join_strips_indented_prompt_bullet_marker() -> None:
    """J drops a space-indented marker even after a plain current line."""
    async with PromptPage("hello\n    - world") as page:
        await page.press("J")
        assert page.text == "hello world"


async def test_join_collapses_space_after_prompt_bullet_marker() -> None:
    """J collapses extra spaces after the pulled-up marker."""
    async with PromptPage("- one\n  -   two") as page:
        await page.press("J")
        assert page.text == "- one two"


async def test_join_prompt_bullet_marker_only_line() -> None:
    """J treats a marker-only next line like a blank line."""
    async with PromptPage("- one\n- ") as page:
        await page.press("J")
        assert page.text == "- one"


async def test_join_keeps_tight_dash() -> None:
    """J preserves a tight dash because it is not a prompt bullet marker."""
    async with PromptPage("hello\n-world") as page:
        await page.press("J")
        assert page.text == "hello -world"


async def test_join_keeps_asterisk_marker() -> None:
    """J strips only prompt hyphen bullet markers."""
    async with PromptPage("hello\n* world") as page:
        await page.press("J")
        assert page.text == "hello * world"


async def test_join_strips_ordered_marker() -> None:
    """J drops an ordered-list marker folded into another line."""
    async with PromptPage("hello\n1. world") as page:
        await page.press("J")
        assert page.text == "hello world"


async def test_join_keeps_thematic_break() -> None:
    """J does not mistake a thematic break for a prompt bullet marker."""
    async with PromptPage("hello\n- - -") as page:
        await page.press("J")
        assert page.text == "hello - - -"


async def test_join_onto_blank_line_keeps_prompt_bullet_marker() -> None:
    """J preserves list structure when a line is only pulled onto a blank."""
    async with PromptPage("- one\n\n- two", cursor=(1, 0)) as page:
        await page.press("J")
        assert page.text == "- one\n- two"


async def test_join_count_strips_each_prompt_bullet_marker() -> None:
    """A counted J strips every marker folded into the current line."""
    async with PromptPage("- one\n- two\n- x") as page:
        await page.press("3", "J")
        assert page.text == "- one two x"


# =============================================================================
# Count support
# =============================================================================


async def test_join_with_count() -> None:
    """3J joins three lines together."""
    async with PromptPage("one\ntwo\nthree\nfour") as page:
        await page.press("3", "J")
        assert page.text == "one two three\nfour"
        assert page.cursor[0] == 0


async def test_join_with_count_exceeding_lines() -> None:
    """Count larger than remaining lines joins as many as possible."""
    async with PromptPage("one\ntwo\nthree") as page:
        await page.press("9", "J")
        assert page.text == "one two three"


# =============================================================================
# Dot-repeat
# =============================================================================


async def test_dot_repeats_join() -> None:
    """Dot repeats J."""
    async with PromptPage("aaa\nbbb\nccc\nddd") as page:
        await page.press("J")
        assert page.text == "aaa bbb\nccc\nddd"

        await page.press(".")
        assert page.text == "aaa bbb ccc\nddd"


async def test_dot_repeats_join_with_prompt_bullet_markers() -> None:
    """Dot repeats marker-aware prompt joins."""
    async with PromptPage("- a\n- b\n- c\n- d") as page:
        await page.press("J")
        assert page.text == "- a b\n- c\n- d"

        await page.press(".")
        assert page.text == "- a b c\n- d"


# =============================================================================
# Virtual-wrap integration
# =============================================================================


async def test_join_does_not_create_background_formatter_state() -> None:
    """J edits text directly; prompt wrapping remains visual-only."""
    async with PromptPage("hello\nworld") as page:
        await page.press("J")
        assert page.text == "hello world"
        assert not hasattr(page.ta, "_format_with_prettier")
        assert not hasattr(page.ta, "_prettier_format_task")
