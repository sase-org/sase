"""Tests for PromptTextArea NORMAL-mode delete operators (d<motion>, D, d^)."""

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _TestApp(App[None]):
    """Minimal app for testing PromptTextArea in isolation."""

    def compose(self) -> ComposeResult:
        yield PromptTextArea(id="ta")


# =============================================================================
# d<motion> operator tests
# =============================================================================


async def test_dd_deletes_current_line() -> None:
    """dd deletes the current line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc"
        ta.cursor_location = (1, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "d")
        assert ta.text == "aaa\nccc"
        assert ta.cursor_location == (1, 0)
        assert ta._vim_mode == "normal"


async def test_2dd_deletes_two_lines() -> None:
    """2dd deletes 2 lines starting from cursor."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc\nddd"
        ta.cursor_location = (1, 0)
        ta._enter_normal_mode()

        await pilot.press("2", "d", "d")
        assert ta.text == "aaa\nddd"
        assert ta.cursor_location == (1, 0)


async def test_dd_last_line() -> None:
    """dd on the last line removes it and moves cursor up."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc"
        ta.cursor_location = (2, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "d")
        assert ta.text == "aaa\nbbb"
        assert ta.cursor_location == (1, 0)


async def test_dd_only_line() -> None:
    """dd on the only line clears the document."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "d")
        assert ta.text == ""
        assert ta.cursor_location == (0, 0)


async def test_dw_deletes_word() -> None:
    """dw deletes from cursor to start of next word."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "w")
        assert ta.text == "two three"
        assert ta.cursor_location == (0, 0)


async def test_d3w_deletes_three_words() -> None:
    """d3w deletes the next 3 words."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three four five"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "3", "w")
        assert ta.text == "four five"
        assert ta.cursor_location == (0, 0)


async def test_d3W_deletes_three_WORDS() -> None:
    """d3W deletes the next 3 WORDs."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three four five"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "3", "W")
        assert ta.text == "four five"
        assert ta.cursor_location == (0, 0)


async def test_2dw_with_count_on_operator() -> None:
    """2dw (count on operator) deletes 2 words."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three four"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("2", "d", "w")
        assert ta.text == "three four"
        assert ta.cursor_location == (0, 0)


async def test_de_deletes_to_end_of_word() -> None:
    """de deletes to end of word (inclusive)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "e")
        assert ta.text == " world"
        assert ta.cursor_location == (0, 0)


async def test_db_deletes_backward_word() -> None:
    """db deletes backward to start of previous word."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three"
        ta.cursor_location = (0, 8)  # start of "three"
        ta._enter_normal_mode()

        await pilot.press("d", "b")
        assert ta.text == "one three"
        assert ta.cursor_location == (0, 4)


async def test_d_dollar_deletes_to_end_of_line() -> None:
    """d$ deletes from cursor to end of line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 5)
        ta._enter_normal_mode()

        await pilot.press("d", "$")
        assert ta.text == "hello"
        assert ta.cursor_location == (0, 5)


async def test_d0_deletes_to_start_of_line() -> None:
    """d0 deletes from cursor to start of line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 6)
        ta._enter_normal_mode()

        await pilot.press("d", "0")
        assert ta.text == "world"
        assert ta.cursor_location == (0, 0)


async def test_dj_deletes_current_and_next_line() -> None:
    """dj deletes current line and the line below (linewise)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc\nddd"
        ta.cursor_location = (1, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "j")
        assert ta.text == "aaa\nddd"
        assert ta.cursor_location == (1, 0)


async def test_dk_deletes_current_and_above_line() -> None:
    """dk deletes current line and the line above (linewise)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc\nddd"
        ta.cursor_location = (2, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "k")
        assert ta.text == "aaa\nddd"
        assert ta.cursor_location == (1, 0)


async def test_dG_deletes_to_end_of_document() -> None:
    """dG deletes from current line to end of document."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc\nddd"
        ta.cursor_location = (2, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "G")
        assert ta.text == "aaa\nbbb"
        assert ta.cursor_location == (1, 0)


async def test_dgg_deletes_to_top_of_document() -> None:
    """dgg deletes from current line to top of document."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc\nddd"
        ta.cursor_location = (2, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "g", "g")
        assert ta.text == "ddd"
        assert ta.cursor_location == (0, 0)


async def test_dl_deletes_character_at_cursor() -> None:
    """dl deletes the character at cursor (like x)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "abcde"
        ta.cursor_location = (0, 2)
        ta._enter_normal_mode()

        await pilot.press("d", "l")
        assert ta.text == "abde"
        assert ta.cursor_location == (0, 2)


async def test_dh_deletes_character_before_cursor() -> None:
    """dh deletes the character before cursor."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "abcde"
        ta.cursor_location = (0, 2)
        ta._enter_normal_mode()

        await pilot.press("d", "h")
        assert ta.text == "acde"
        assert ta.cursor_location == (0, 1)


# =============================================================================
# D (delete to end of line) tests
# =============================================================================


async def test_D_deletes_to_end_of_line() -> None:
    """D deletes from cursor to end of line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 5)
        ta._enter_normal_mode()

        await pilot.press("D")
        assert ta.text == "hello"
        assert ta._vim_mode == "normal"


async def test_D_at_start_of_line_deletes_entire_line_content() -> None:
    """D from column 0 deletes all content on the line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc"
        ta.cursor_location = (1, 0)
        ta._enter_normal_mode()

        await pilot.press("D")
        assert ta.text == "aaa\n\nccc"
        assert ta.cursor_location == (1, 0)


async def test_D_at_end_of_line_is_noop() -> None:
    """D at end of line deletes nothing."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello"
        ta.cursor_location = (0, 5)
        ta._enter_normal_mode()

        await pilot.press("D")
        assert ta.text == "hello"
        assert ta._vim_mode == "normal"


# =============================================================================
# d^ (delete to first non-whitespace) test
# =============================================================================


async def test_d_caret_deletes_to_first_nonwhitespace() -> None:
    """d^ deletes from cursor to first non-whitespace character."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "    hello"
        ta.cursor_location = (0, 7)
        ta._enter_normal_mode()

        await pilot.press("d", "^")
        assert ta.text == "    lo"
        assert ta.cursor_location == (0, 4)
