"""Tests for PromptTextArea NORMAL-mode change operators, operator state, and undo."""

from sase.ace.testing import PromptPage


def _lines(n: int = 20) -> str:
    """Generate n lines of text for testing vertical motions."""
    return "\n".join(f"line {i}" for i in range(n))


# =============================================================================
# c<motion> operator tests
# =============================================================================


async def test_cc_changes_current_line() -> None:
    """cc clears current line and enters insert mode."""
    async with PromptPage("aaa\nbbb\nccc", cursor=(1, 0)) as page:
        await page.press("c", "c")
        assert page.mode == "insert"
        lines = page.text.split("\n")
        assert lines[0] == "aaa"
        assert lines[1] == ""
        assert lines[2] == "ccc"
        assert page.cursor == (1, 0)


async def test_cw_changes_word() -> None:
    """cw deletes to next word start and enters insert mode."""
    async with PromptPage("one two three") as page:
        await page.press("c", "w")
        assert page.mode == "insert"
        assert page.text == "two three"
        assert page.cursor == (0, 0)


async def test_c_dollar_changes_to_end_of_line() -> None:
    """c$ deletes to end of line and enters insert mode."""
    async with PromptPage("hello world", cursor=(0, 5)) as page:
        await page.press("c", "$")
        assert page.mode == "insert"
        assert page.text == "hello"
        assert page.cursor == (0, 5)


async def test_ce_changes_to_end_of_word() -> None:
    """ce deletes through end of word (inclusive) and enters insert mode."""
    async with PromptPage("hello world") as page:
        await page.press("c", "e")
        assert page.mode == "insert"
        assert page.text == " world"


async def test_c5j_changes_current_and_five_below() -> None:
    """c5j deletes current + 5 below, enters insert mode."""
    async with PromptPage(_lines(10), cursor=(2, 0)) as page:
        await page.press("c", "5", "j")
        # Lines 2..7 replaced with empty line, lines 0,1 and 8,9 remain
        assert page.mode == "insert"
        lines = page.text.split("\n")
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
    async with PromptPage("hello world", cursor=(0, 5)) as page:
        await page.press("C")
        assert page.text == "hello"
        assert page.mode == "insert"


async def test_C_at_end_of_line_enters_insert_mode() -> None:
    """C at end of line just enters insert mode."""
    async with PromptPage("hello", cursor=(0, 5)) as page:
        await page.press("C")
        assert page.text == "hello"
        assert page.mode == "insert"


async def test_C_multiline_only_affects_current_line() -> None:
    """C only deletes to end of current line, not into next line."""
    async with PromptPage("aaa\nbbb\nccc", cursor=(1, 1)) as page:
        await page.press("C")
        assert page.text == "aaa\nb\nccc"
        assert page.mode == "insert"


# =============================================================================
# Operator state / cancellation
# =============================================================================


async def test_escape_cancels_pending_operator() -> None:
    """Pressing Escape after d cancels the operator."""
    async with PromptPage("hello world") as page:
        await page.press("d")
        assert page.ta._pending_operator == "d"
        await page.press("escape")
        assert page.ta._pending_operator == ""
        assert page.mode == "normal"
        assert page.text == "hello world"


async def test_operator_cleared_after_execution() -> None:
    """After dw, a bare w just moves (no deletion)."""
    async with PromptPage("one two three four") as page:
        await page.press("d", "w")
        assert page.text == "two three four"
        assert page.ta._pending_operator == ""

        await page.press("w")
        # Just moves to next word, no deletion
        assert page.text == "two three four"


# =============================================================================
# Undo (u) tests
# =============================================================================


async def test_u_undoes_dw() -> None:
    """u after dw restores the deleted word."""
    async with PromptPage("one two three") as page:
        await page.press("d", "w")
        assert page.text == "two three"

        await page.press("u")
        assert page.text == "one two three"
        assert page.mode == "normal"


async def test_u_undoes_dd() -> None:
    """u after dd restores the deleted line."""
    async with PromptPage("aaa\nbbb\nccc", cursor=(1, 0)) as page:
        await page.press("d", "d")
        assert page.text == "aaa\nccc"

        await page.press("u")
        assert page.text == "aaa\nbbb\nccc"


async def test_u_undoes_cw() -> None:
    """u after cw + typed text restores original content."""
    async with PromptPage("one two three") as page:
        await page.press("c", "w")
        assert page.mode == "insert"
        assert page.text == "two three"

        # Type replacement text
        await page.press("X", "X", "X", " ")
        assert page.text == "XXX two three"

        # Back to normal mode, then undo
        await page.press("escape")
        await page.press("u")
        # Undo the typed text first
        assert page.text == "two three"
        await page.press("u")
        # Undo the deletion
        assert page.text == "one two three"


async def test_u_noop_when_nothing_to_undo() -> None:
    """u with no edit history does nothing."""
    async with PromptPage("hello") as page:
        await page.press("u")
        assert page.text == "hello"
        assert page.mode == "normal"
