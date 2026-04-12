"""Tests for the ace testing DSL (AcePage, PromptPage)."""

import pytest

from sase.ace.testing import AcePage, PromptPage, make_changespec


async def test_ace_page_initial_state() -> None:
    """AcePage returns expected state dict after entering context."""
    async with AcePage() as page:
        state = page.state
        assert state["idx"] == 0
        assert state["total"] == 3
        assert state["tab"] == "changespecs"
        assert state["modal"] is None
        assert state["selected"]["name"] == "feature_a"


async def test_ace_page_press() -> None:
    """Pressing 'j' changes the current index."""
    async with AcePage() as page:
        assert page.state["idx"] == 0
        await page.press("j")
        assert page.state["idx"] == 1


async def test_ace_page_screen() -> None:
    """Screen property returns non-empty string."""
    async with AcePage() as page:
        screen = page.screen
        assert isinstance(screen, str)
        assert len(screen) > 0


async def test_ace_page_custom_changespecs() -> None:
    """Passing custom changespecs overrides defaults."""
    custom = [
        make_changespec(name="custom_a"),
        make_changespec(name="custom_b"),
    ]
    async with AcePage(query='"custom"', changespecs=custom) as page:
        state = page.state
        assert state["total"] == 2
        assert state["selected"]["name"] == "custom_a"


async def test_expect_state_passes() -> None:
    """expect_state succeeds when the value matches immediately."""
    async with AcePage() as page:
        await page.expect_state("idx", 0)
        await page.expect_state("total", 3)
        await page.expect_state("tab", "changespecs")


async def test_expect_state_fails_on_timeout() -> None:
    """expect_state raises AssertionError when the value never matches."""
    async with AcePage() as page:
        with pytest.raises(AssertionError, match="expect_state.*timed out"):
            await page.expect_state("idx", 999, timeout=0.1)


async def test_expect_state_nested_key() -> None:
    """Dot-notation like 'selected.name' resolves nested dict keys."""
    async with AcePage() as page:
        await page.expect_state("selected.name", "feature_a")


async def test_expect_modal() -> None:
    """expect_modal succeeds after opening the query modal."""
    async with AcePage() as page:
        await page.press("slash")
        await page.expect_modal("QueryEditModal")


async def test_expect_no_modal() -> None:
    """expect_no_modal succeeds when no modal is shown."""
    async with AcePage() as page:
        await page.expect_no_modal()


async def test_expect_screen_contains() -> None:
    """expect_screen_contains succeeds when text is present in screen output."""
    async with AcePage() as page:
        # Screen in headless test mode is whitespace; verify the polling
        # mechanism works by checking for a character that IS present.
        await page.expect_screen_contains(" ")


async def test_expect_screen_contains_timeout() -> None:
    """expect_screen_contains raises AssertionError when text is never found."""
    async with AcePage() as page:
        with pytest.raises(AssertionError, match="expect_screen_contains.*timed out"):
            await page.expect_screen_contains("nonexistent_xyz", timeout=0.1)


async def test_expect_screen_not_contains() -> None:
    """expect_screen_not_contains succeeds when text is absent."""
    async with AcePage() as page:
        await page.expect_screen_not_contains("nonexistent_xyz")


async def test_wait_for() -> None:
    """wait_for succeeds with a custom predicate."""
    async with AcePage() as page:
        await page.wait_for(lambda state: state["total"] > 0)


# =============================================================================
# PromptPage tests
# =============================================================================


async def test_prompt_page_initial_state() -> None:
    """PromptPage sets text, cursor, and mode on entry."""
    async with PromptPage("hello world", cursor=(0, 5)) as page:
        assert page.text == "hello world"
        assert page.cursor == (0, 5)
        assert page.mode == "normal"


async def test_prompt_page_press() -> None:
    """Pressing keys through PromptPage works."""
    async with PromptPage("one two three", cursor=(0, 0)) as page:
        await page.press("d", "w")
        assert page.text == "two three"


async def test_prompt_page_insert_mode() -> None:
    """PromptPage with mode='insert' does not enter normal mode."""
    async with PromptPage("hello", mode="insert") as page:
        assert page.mode == "insert"


async def test_prompt_page_ta_access() -> None:
    """page.ta gives direct access to the PromptTextArea widget."""
    async with PromptPage("test") as page:
        assert page.ta.text == "test"
        assert page.ta._vim_mode == "normal"


async def test_prompt_page_cursor_setter() -> None:
    """page.cursor can be set mid-test."""
    async with PromptPage("hello\nworld", cursor=(0, 0)) as page:
        page.cursor = (1, 3)
        assert page.cursor == (1, 3)
