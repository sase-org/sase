"""Tests for PromptTextArea NORMAL-mode count prefix on motions and scrolling."""

from sase.ace.testing import PromptPage


def _lines(n: int = 20) -> str:
    """Generate n lines of text for testing vertical motions."""
    return "\n".join(f"line {i}" for i in range(n))


# --- Count prefix with j/k ---


async def test_count_j() -> None:
    """5j moves cursor down 5 lines."""
    async with PromptPage(_lines(20)) as page:
        await page.press("5", "j")
        assert page.cursor[0] == 5


async def test_count_k() -> None:
    """5k moves cursor up 5 lines."""
    async with PromptPage(_lines(20), cursor=(10, 0)) as page:
        await page.press("5", "k")
        assert page.cursor[0] == 5


async def test_count_j_clamps_at_bottom() -> None:
    """15j from line 15 of 20 lines clamps to last line."""
    async with PromptPage(_lines(20), cursor=(15, 0)) as page:
        await page.press("1", "5", "j")
        assert page.cursor[0] == 19


async def test_count_k_clamps_at_top() -> None:
    """15k from line 5 clamps to line 0."""
    async with PromptPage(_lines(20), cursor=(5, 0)) as page:
        await page.press("1", "5", "k")
        assert page.cursor[0] == 0


# --- Count prefix with h/l ---


async def test_count_h() -> None:
    """5h moves cursor left 5 columns."""
    async with PromptPage("abcdefghij", cursor=(0, 8)) as page:
        await page.press("5", "h")
        assert page.cursor == (0, 3)


async def test_count_l() -> None:
    """5l moves cursor right 5 columns."""
    async with PromptPage("abcdefghij") as page:
        await page.press("5", "l")
        assert page.cursor == (0, 5)


# --- Count prefix with word motions ---


async def test_count_w() -> None:
    """3w moves forward 3 word starts."""
    async with PromptPage("one two three four five") as page:
        await page.press("3", "w")
        assert page.cursor == (0, 14)  # start of "four"


async def test_count_b() -> None:
    """3b moves backward 3 word starts."""
    async with PromptPage("one two three four five", cursor=(0, 19)) as page:
        await page.press("3", "b")
        assert page.cursor == (0, 4)  # start of "two"


async def test_count_e() -> None:
    """3e moves forward to end of 3rd word."""
    async with PromptPage("one two three four five") as page:
        await page.press("3", "e")
        assert page.cursor == (0, 12)  # end of "three"


# --- G (go-to-line / go-to-end) ---


async def test_G_without_count_goes_to_last_line() -> None:
    """G without count goes to last line."""
    async with PromptPage(_lines(20)) as page:
        await page.press("G")
        assert page.cursor[0] == 19


async def test_G_with_count_goes_to_line() -> None:
    """5G goes to line 5 (1-indexed, so row 4)."""
    async with PromptPage(_lines(20)) as page:
        await page.press("5", "G")
        assert page.cursor[0] == 4


async def test_G_with_count_clamps_to_last() -> None:
    """99G on a 20-line document clamps to line 19."""
    async with PromptPage(_lines(20)) as page:
        await page.press("9", "9", "G")
        assert page.cursor[0] == 19


# --- gg (go-to-line / go-to-first) ---


async def test_gg_without_count_goes_to_first_line() -> None:
    """gg without count goes to first line."""
    async with PromptPage(_lines(20), cursor=(15, 0)) as page:
        await page.press("g", "g")
        assert page.cursor == (0, 0)


async def test_gg_with_count_goes_to_line() -> None:
    """5gg goes to line 5 (1-indexed, so row 4)."""
    async with PromptPage(_lines(20)) as page:
        await page.press("5", "g", "g")
        assert page.cursor[0] == 4


async def test_gg_with_count_clamps_to_last() -> None:
    """99gg on a 20-line document clamps to line 19."""
    async with PromptPage(_lines(20)) as page:
        await page.press("9", "9", "g", "g")
        assert page.cursor[0] == 19


# --- Count prefix cleared after use ---


async def test_count_cleared_after_use() -> None:
    """After 2j, a bare j moves only 1 line."""
    async with PromptPage(_lines(20)) as page:
        await page.press("2", "j")
        assert page.cursor[0] == 2

        await page.press("j")
        assert page.cursor[0] == 3


# --- Zero handling ---


async def test_zero_without_prefix_moves_to_start_of_line() -> None:
    """0 without an existing count prefix moves to column 0."""
    async with PromptPage("hello world", cursor=(0, 6)) as page:
        await page.press("0")
        assert page.cursor == (0, 0)


async def test_zero_appends_to_count() -> None:
    """10j should move down 10 lines (0 appends to count started by 1)."""
    async with PromptPage(_lines(20)) as page:
        await page.press("1", "0", "j")
        assert page.cursor[0] == 10


# =============================================================================
# Half-page scroll (ctrl+d / ctrl+u) tests
# =============================================================================


async def test_ctrl_d_scrolls_down_half_page() -> None:
    """ctrl+d moves cursor down by half the visible height."""
    async with PromptPage(_lines(50), size=(80, 24)) as page:
        half = page.ta.size.height // 2
        await page.press("ctrl+d")
        assert page.cursor[0] == half
        assert page.mode == "normal"


async def test_ctrl_u_scrolls_up_half_page() -> None:
    """ctrl+u moves cursor up by half the visible height."""
    async with PromptPage(_lines(50), cursor=(40, 0), size=(80, 24)) as page:
        half = page.ta.size.height // 2
        await page.press("ctrl+u")
        assert page.cursor[0] == 40 - half
        assert page.mode == "normal"


async def test_ctrl_d_clamps_at_bottom() -> None:
    """ctrl+d from near the bottom clamps to the last line."""
    async with PromptPage(_lines(20), cursor=(18, 0), size=(80, 24)) as page:
        await page.press("ctrl+d")
        assert page.cursor[0] == 19


async def test_ctrl_u_clamps_at_top() -> None:
    """ctrl+u from near the top clamps to line 0."""
    async with PromptPage(_lines(50), cursor=(2, 0), size=(80, 24)) as page:
        await page.press("ctrl+u")
        assert page.cursor[0] == 0


async def test_ctrl_d_preserves_column() -> None:
    """ctrl+d preserves the cursor column."""
    async with PromptPage(_lines(50), cursor=(0, 3), size=(80, 24)) as page:
        await page.press("ctrl+d")
        assert page.cursor[1] == 3
