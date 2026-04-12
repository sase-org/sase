"""Tests for PromptTextArea NORMAL-mode word text objects (iw, aw, iW, aW)."""

from sase.ace.testing import PromptPage


# --- diw (delete inner word) ---


async def test_diw_middle_of_word() -> None:
    """diw deletes the word under the cursor."""
    async with PromptPage("hello world foo", cursor=(0, 7)) as page:
        await page.press("d", "i", "w")
        assert page.text == "hello  foo"


async def test_diw_start_of_word() -> None:
    """diw at start of word deletes the whole word."""
    async with PromptPage("hello world foo", cursor=(0, 6)) as page:
        await page.press("d", "i", "w")
        assert page.text == "hello  foo"


async def test_diw_on_whitespace() -> None:
    """diw on whitespace deletes the whitespace group."""
    async with PromptPage("hello   world", cursor=(0, 6)) as page:
        await page.press("d", "i", "w")
        assert page.text == "helloworld"


async def test_diw_on_punctuation() -> None:
    """diw on punctuation deletes the punctuation group."""
    async with PromptPage("hello...world", cursor=(0, 6)) as page:
        await page.press("d", "i", "w")
        assert page.text == "helloworld"


# --- daw (delete a word) ---


async def test_daw_deletes_word_and_trailing_space() -> None:
    """daw deletes the word plus trailing whitespace."""
    async with PromptPage("hello world foo", cursor=(0, 7)) as page:
        await page.press("d", "a", "w")
        assert page.text == "hello foo"


async def test_daw_deletes_word_and_leading_space_at_end() -> None:
    """daw at end of line includes leading whitespace when no trailing."""
    async with PromptPage("hello world", cursor=(0, 6)) as page:
        await page.press("d", "a", "w")
        assert page.text == "hello"


async def test_daw_on_first_word() -> None:
    """daw on first word includes trailing whitespace."""
    async with PromptPage("hello world", cursor=(0, 2)) as page:
        await page.press("d", "a", "w")
        assert page.text == "world"


# --- diW (delete inner WORD) ---


async def test_diW_deletes_WORD() -> None:
    """diW deletes the WORD (non-whitespace run) under cursor."""
    async with PromptPage("hello foo.bar baz", cursor=(0, 8)) as page:
        await page.press("d", "i", "W")
        assert page.text == "hello  baz"


# --- daW (delete a WORD) ---


async def test_daW_deletes_WORD_and_trailing_space() -> None:
    """daW deletes the WORD plus trailing whitespace."""
    async with PromptPage("hello foo.bar baz", cursor=(0, 8)) as page:
        await page.press("d", "a", "W")
        assert page.text == "hello baz"


async def test_daW_at_end_includes_leading_space() -> None:
    """daW on last WORD includes leading whitespace."""
    async with PromptPage("hello foo.bar", cursor=(0, 8)) as page:
        await page.press("d", "a", "W")
        assert page.text == "hello"


# --- ciw (change inner word) ---


async def test_ciw_enters_insert_mode() -> None:
    """ciw deletes the word and enters insert mode."""
    async with PromptPage("hello world foo", cursor=(0, 7)) as page:
        await page.press("c", "i", "w")
        assert page.text == "hello  foo"
        assert page.mode == "insert"


# --- Count support ---


async def test_d2iw() -> None:
    """d2iw deletes two groups."""
    async with PromptPage("hello world foo") as page:
        await page.press("d", "2", "i", "w")
        # iw with count=2: "hello" (word) + " " (space) = "hello "
        assert page.text == "world foo"


# --- Dot-repeat ---


async def test_dot_repeat_daw() -> None:
    """daw followed by . repeats the deletion."""
    async with PromptPage("one two three four") as page:
        await page.press("d", "a", "w")
        assert page.text == "two three four"

        await page.press(".")
        assert page.text == "three four"


# --- Edge cases ---


async def test_diw_single_word() -> None:
    """diw on a single word deletes the entire content."""
    async with PromptPage("hello", cursor=(0, 2)) as page:
        await page.press("d", "i", "w")
        assert page.text == ""


async def test_daw_single_word() -> None:
    """daw on a single word deletes the entire content."""
    async with PromptPage("hello", cursor=(0, 2)) as page:
        await page.press("d", "a", "w")
        assert page.text == ""
