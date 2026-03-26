"""Tests for PromptTextArea NORMAL-mode word text objects (iw, aw, iW, aW)."""

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _TestApp(App[None]):
    """Minimal app for testing PromptTextArea in isolation."""

    def compose(self) -> ComposeResult:
        yield PromptTextArea(id="ta")


# --- diw (delete inner word) ---


async def test_diw_middle_of_word() -> None:
    """diw deletes the word under the cursor."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world foo"
        ta.cursor_location = (0, 7)  # on 'o' of "world"
        ta._enter_normal_mode()

        await pilot.press("d", "i", "w")
        assert ta.text == "hello  foo"


async def test_diw_start_of_word() -> None:
    """diw at start of word deletes the whole word."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world foo"
        ta.cursor_location = (0, 6)  # on 'w' of "world"
        ta._enter_normal_mode()

        await pilot.press("d", "i", "w")
        assert ta.text == "hello  foo"


async def test_diw_on_whitespace() -> None:
    """diw on whitespace deletes the whitespace group."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello   world"
        ta.cursor_location = (0, 6)  # on space between words
        ta._enter_normal_mode()

        await pilot.press("d", "i", "w")
        assert ta.text == "helloworld"


async def test_diw_on_punctuation() -> None:
    """diw on punctuation deletes the punctuation group."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello...world"
        ta.cursor_location = (0, 6)  # on '.' in "..."
        ta._enter_normal_mode()

        await pilot.press("d", "i", "w")
        assert ta.text == "helloworld"


# --- daw (delete a word) ---


async def test_daw_deletes_word_and_trailing_space() -> None:
    """daw deletes the word plus trailing whitespace."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world foo"
        ta.cursor_location = (0, 7)  # on 'o' of "world"
        ta._enter_normal_mode()

        await pilot.press("d", "a", "w")
        assert ta.text == "hello foo"


async def test_daw_deletes_word_and_leading_space_at_end() -> None:
    """daw at end of line includes leading whitespace when no trailing."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 6)  # on 'w' of "world"
        ta._enter_normal_mode()

        await pilot.press("d", "a", "w")
        assert ta.text == "hello"


async def test_daw_on_first_word() -> None:
    """daw on first word includes trailing whitespace."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 2)  # on 'l' of "hello"
        ta._enter_normal_mode()

        await pilot.press("d", "a", "w")
        assert ta.text == "world"


# --- diW (delete inner WORD) ---


async def test_diW_deletes_WORD() -> None:
    """diW deletes the WORD (non-whitespace run) under cursor."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello foo.bar baz"
        ta.cursor_location = (0, 8)  # on '.' in "foo.bar"
        ta._enter_normal_mode()

        await pilot.press("d", "i", "W")
        assert ta.text == "hello  baz"


# --- daW (delete a WORD) ---


async def test_daW_deletes_WORD_and_trailing_space() -> None:
    """daW deletes the WORD plus trailing whitespace."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello foo.bar baz"
        ta.cursor_location = (0, 8)  # on '.' in "foo.bar"
        ta._enter_normal_mode()

        await pilot.press("d", "a", "W")
        assert ta.text == "hello baz"


async def test_daW_at_end_includes_leading_space() -> None:
    """daW on last WORD includes leading whitespace."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello foo.bar"
        ta.cursor_location = (0, 8)  # on '.' in "foo.bar"
        ta._enter_normal_mode()

        await pilot.press("d", "a", "W")
        assert ta.text == "hello"


# --- ciw (change inner word) ---


async def test_ciw_enters_insert_mode() -> None:
    """ciw deletes the word and enters insert mode."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world foo"
        ta.cursor_location = (0, 7)  # on 'o' of "world"
        ta._enter_normal_mode()

        await pilot.press("c", "i", "w")
        assert ta.text == "hello  foo"
        assert ta._vim_mode == "insert"


# --- Count support ---


async def test_d2iw() -> None:
    """d2iw deletes two groups."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world foo"
        ta.cursor_location = (0, 0)  # on 'h' of "hello"
        ta._enter_normal_mode()

        await pilot.press("d", "2", "i", "w")
        # iw with count=2: "hello" (word) + " " (space) = "hello "
        assert ta.text == "world foo"


# --- Dot-repeat ---


async def test_dot_repeat_daw() -> None:
    """daw followed by . repeats the deletion."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three four"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "a", "w")
        assert ta.text == "two three four"

        await pilot.press(".")
        assert ta.text == "three four"


# --- Edge cases ---


async def test_diw_single_word() -> None:
    """diw on a single word deletes the entire content."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello"
        ta.cursor_location = (0, 2)
        ta._enter_normal_mode()

        await pilot.press("d", "i", "w")
        assert ta.text == ""


async def test_daw_single_word() -> None:
    """daw on a single word deletes the entire content."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello"
        ta.cursor_location = (0, 2)
        ta._enter_normal_mode()

        await pilot.press("d", "a", "w")
        assert ta.text == ""
