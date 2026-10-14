"""PromptPage behavior tests."""

from sase.ace.testing import PromptPage


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
