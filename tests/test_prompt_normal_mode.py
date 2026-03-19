"""Tests for PromptTextArea NORMAL-mode count prefix on all motions."""

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _TestApp(App[None]):
    """Minimal app for testing PromptTextArea in isolation."""

    def compose(self) -> ComposeResult:
        yield PromptTextArea(id="ta")


def _lines(n: int = 20) -> str:
    """Generate n lines of text for testing vertical motions."""
    return "\n".join(f"line {i}" for i in range(n))


# --- Count prefix with j/k ---


async def test_count_j() -> None:
    """5j moves cursor down 5 lines."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("5", "j")
        assert ta.cursor_location[0] == 5


async def test_count_k() -> None:
    """5k moves cursor up 5 lines."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (10, 0)
        ta._enter_normal_mode()

        await pilot.press("5", "k")
        assert ta.cursor_location[0] == 5


async def test_count_j_clamps_at_bottom() -> None:
    """15j from line 15 of 20 lines clamps to last line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (15, 0)
        ta._enter_normal_mode()

        await pilot.press("1", "5", "j")
        assert ta.cursor_location[0] == 19


async def test_count_k_clamps_at_top() -> None:
    """15k from line 5 clamps to line 0."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (5, 0)
        ta._enter_normal_mode()

        await pilot.press("1", "5", "k")
        assert ta.cursor_location[0] == 0


# --- Count prefix with h/l ---


async def test_count_h() -> None:
    """5h moves cursor left 5 columns."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "abcdefghij"
        ta.cursor_location = (0, 8)
        ta._enter_normal_mode()

        await pilot.press("5", "h")
        assert ta.cursor_location == (0, 3)


async def test_count_l() -> None:
    """5l moves cursor right 5 columns."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "abcdefghij"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("5", "l")
        assert ta.cursor_location == (0, 5)


# --- Count prefix with word motions ---


async def test_count_w() -> None:
    """3w moves forward 3 word starts."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three four five"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("3", "w")
        assert ta.cursor_location == (0, 14)  # start of "four"


async def test_count_b() -> None:
    """3b moves backward 3 word starts."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three four five"
        ta.cursor_location = (0, 19)  # start of "five"
        ta._enter_normal_mode()

        await pilot.press("3", "b")
        assert ta.cursor_location == (0, 4)  # start of "two"


async def test_count_e() -> None:
    """3e moves forward to end of 3rd word."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three four five"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("3", "e")
        assert ta.cursor_location == (0, 12)  # end of "three"


# --- G (go-to-line / go-to-end) ---


async def test_G_without_count_goes_to_last_line() -> None:
    """G without count goes to last line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("G")
        assert ta.cursor_location[0] == 19


async def test_G_with_count_goes_to_line() -> None:
    """5G goes to line 5 (1-indexed, so row 4)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("5", "G")
        assert ta.cursor_location[0] == 4


async def test_G_with_count_clamps_to_last() -> None:
    """99G on a 20-line document clamps to line 19."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("9", "9", "G")
        assert ta.cursor_location[0] == 19


# --- gg (go-to-line / go-to-first) ---


async def test_gg_without_count_goes_to_first_line() -> None:
    """gg without count goes to first line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (15, 0)
        ta._enter_normal_mode()

        await pilot.press("g", "g")
        assert ta.cursor_location == (0, 0)


async def test_gg_with_count_goes_to_line() -> None:
    """5gg goes to line 5 (1-indexed, so row 4)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("5", "g", "g")
        assert ta.cursor_location[0] == 4


async def test_gg_with_count_clamps_to_last() -> None:
    """99gg on a 20-line document clamps to line 19."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("9", "9", "g", "g")
        assert ta.cursor_location[0] == 19


# --- Count prefix cleared after use ---


async def test_count_cleared_after_use() -> None:
    """After 2j, a bare j moves only 1 line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("2", "j")
        assert ta.cursor_location[0] == 2

        await pilot.press("j")
        assert ta.cursor_location[0] == 3


# --- Zero handling ---


async def test_zero_without_prefix_moves_to_start_of_line() -> None:
    """0 without an existing count prefix moves to column 0."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 6)
        ta._enter_normal_mode()

        await pilot.press("0")
        assert ta.cursor_location == (0, 0)


async def test_zero_appends_to_count() -> None:
    """10j should move down 10 lines (0 appends to count started by 1)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("1", "0", "j")
        assert ta.cursor_location[0] == 10


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


async def test_c5j_changes_current_and_five_below() -> None:
    """c5j deletes current + 5 below, enters insert mode."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(10)
        ta.cursor_location = (2, 0)
        ta._enter_normal_mode()

        await pilot.press("c", "5", "j")
        # Lines 2..7 replaced with empty line, lines 0,1 and 8,9 remain
        assert ta._vim_mode == "insert"
        lines = ta.text.split("\n")
        assert lines[0] == "line 0"
        assert lines[1] == "line 1"
        assert lines[2] == ""  # empty line from change
        assert lines[3] == "line 8"
        assert lines[4] == "line 9"


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
# c<motion> operator tests
# =============================================================================


async def test_cc_changes_current_line() -> None:
    """cc clears current line and enters insert mode."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc"
        ta.cursor_location = (1, 0)
        ta._enter_normal_mode()

        await pilot.press("c", "c")
        assert ta._vim_mode == "insert"
        lines = ta.text.split("\n")
        assert lines[0] == "aaa"
        assert lines[1] == ""
        assert lines[2] == "ccc"
        assert ta.cursor_location == (1, 0)


async def test_cw_changes_word() -> None:
    """cw deletes to next word start and enters insert mode."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("c", "w")
        assert ta._vim_mode == "insert"
        assert ta.text == "two three"
        assert ta.cursor_location == (0, 0)


async def test_c_dollar_changes_to_end_of_line() -> None:
    """c$ deletes to end of line and enters insert mode."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 5)
        ta._enter_normal_mode()

        await pilot.press("c", "$")
        assert ta._vim_mode == "insert"
        assert ta.text == "hello"
        assert ta.cursor_location == (0, 5)


async def test_ce_changes_to_end_of_word() -> None:
    """ce deletes through end of word (inclusive) and enters insert mode."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("c", "e")
        assert ta._vim_mode == "insert"
        assert ta.text == " world"


# =============================================================================
# Operator state / cancellation
# =============================================================================


async def test_escape_cancels_pending_operator() -> None:
    """Pressing Escape after d cancels the operator."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d")
        assert ta._pending_operator == "d"
        await pilot.press("escape")
        assert ta._pending_operator == ""
        assert ta._vim_mode == "normal"
        assert ta.text == "hello world"


async def test_operator_cleared_after_execution() -> None:
    """After dw, a bare w just moves (no deletion)."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three four"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "w")
        assert ta.text == "two three four"
        assert ta._pending_operator == ""

        await pilot.press("w")
        # Just moves to next word, no deletion
        assert ta.text == "two three four"


# =============================================================================
# Half-page scroll (ctrl+d / ctrl+u) tests
# =============================================================================


async def test_ctrl_d_scrolls_down_half_page() -> None:
    """ctrl+d moves cursor down by half the visible height."""
    app = _TestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(50)
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        half = ta.size.height // 2
        await pilot.press("ctrl+d")
        assert ta.cursor_location[0] == half
        assert ta._vim_mode == "normal"


async def test_ctrl_u_scrolls_up_half_page() -> None:
    """ctrl+u moves cursor up by half the visible height."""
    app = _TestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(50)
        ta.cursor_location = (40, 0)
        ta._enter_normal_mode()

        half = ta.size.height // 2
        await pilot.press("ctrl+u")
        assert ta.cursor_location[0] == 40 - half
        assert ta._vim_mode == "normal"


async def test_ctrl_d_clamps_at_bottom() -> None:
    """ctrl+d from near the bottom clamps to the last line."""
    app = _TestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(20)
        ta.cursor_location = (18, 0)
        ta._enter_normal_mode()

        await pilot.press("ctrl+d")
        assert ta.cursor_location[0] == 19


async def test_ctrl_u_clamps_at_top() -> None:
    """ctrl+u from near the top clamps to line 0."""
    app = _TestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(50)
        ta.cursor_location = (2, 0)
        ta._enter_normal_mode()

        await pilot.press("ctrl+u")
        assert ta.cursor_location[0] == 0


async def test_ctrl_d_preserves_column() -> None:
    """ctrl+d preserves the cursor column."""
    app = _TestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = _lines(50)
        ta.cursor_location = (0, 3)
        ta._enter_normal_mode()

        await pilot.press("ctrl+d")
        assert ta.cursor_location[1] == 3


# =============================================================================
# Undo (u) tests
# =============================================================================


async def test_u_undoes_dw() -> None:
    """u after dw restores the deleted word."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "w")
        assert ta.text == "two three"

        await pilot.press("u")
        assert ta.text == "one two three"
        assert ta._vim_mode == "normal"


async def test_u_undoes_dd() -> None:
    """u after dd restores the deleted line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc"
        ta.cursor_location = (1, 0)
        ta._enter_normal_mode()

        await pilot.press("d", "d")
        assert ta.text == "aaa\nccc"

        await pilot.press("u")
        assert ta.text == "aaa\nbbb\nccc"


async def test_u_undoes_cw() -> None:
    """u after cw + typed text restores original content."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "one two three"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("c", "w")
        assert ta._vim_mode == "insert"
        assert ta.text == "two three"

        # Type replacement text
        await pilot.press("X", "X", "X", " ")
        assert ta.text == "XXX two three"

        # Back to normal mode, then undo
        await pilot.press("escape")
        await pilot.press("u")
        # Undo the typed text first
        assert ta.text == "two three"
        await pilot.press("u")
        # Undo the deletion
        assert ta.text == "one two three"


async def test_u_noop_when_nothing_to_undo() -> None:
    """u with no edit history does nothing."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello"
        ta.cursor_location = (0, 0)
        ta._enter_normal_mode()

        await pilot.press("u")
        assert ta.text == "hello"
        assert ta._vim_mode == "normal"


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
