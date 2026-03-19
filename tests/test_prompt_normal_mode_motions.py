"""Tests for PromptTextArea NORMAL-mode count prefix on motions and scrolling."""

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
