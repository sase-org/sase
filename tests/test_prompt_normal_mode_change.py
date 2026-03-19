"""Tests for PromptTextArea NORMAL-mode change operators, operator state, and undo."""

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _TestApp(App[None]):
    """Minimal app for testing PromptTextArea in isolation."""

    def compose(self) -> ComposeResult:
        yield PromptTextArea(id="ta")


def _lines(n: int = 20) -> str:
    """Generate n lines of text for testing vertical motions."""
    return "\n".join(f"line {i}" for i in range(n))


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


# =============================================================================
# C (change to end of line) tests
# =============================================================================


async def test_C_changes_to_end_of_line() -> None:
    """C deletes to end of line and enters insert mode."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello world"
        ta.cursor_location = (0, 5)
        ta._enter_normal_mode()

        await pilot.press("C")
        assert ta.text == "hello"
        assert ta._vim_mode == "insert"


async def test_C_at_end_of_line_enters_insert_mode() -> None:
    """C at end of line just enters insert mode."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "hello"
        ta.cursor_location = (0, 5)
        ta._enter_normal_mode()

        await pilot.press("C")
        assert ta.text == "hello"
        assert ta._vim_mode == "insert"


async def test_C_multiline_only_affects_current_line() -> None:
    """C only deletes to end of current line, not into next line."""
    app = _TestApp()
    async with app.run_test() as pilot:
        ta = app.query_one("#ta", PromptTextArea)
        ta.text = "aaa\nbbb\nccc"
        ta.cursor_location = (1, 1)
        ta._enter_normal_mode()

        await pilot.press("C")
        assert ta.text == "aaa\nb\nccc"
        assert ta._vim_mode == "insert"


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
