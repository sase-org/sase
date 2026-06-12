"""Tests for PromptTextArea NORMAL-mode paragraph motions and text objects."""

from sase.ace.testing import PromptPage


TEXT = "alpha\nbeta\n\ncharlie\n  delta\n\n\nend"


async def test_paragraph_motions_jump_to_blank_boundaries() -> None:
    """} and { move to paragraph-separating blank lines."""
    async with PromptPage(TEXT) as page:
        await page.press("}")
        assert page.cursor == (2, 0)

        await page.press("}")
        assert page.cursor == (5, 0)

        await page.press("{")
        assert page.cursor == (2, 0)


async def test_counted_paragraph_motion_treats_blank_block_as_one_boundary() -> None:
    """A count skips paragraph boundaries, not every line in a blank block."""
    async with PromptPage(TEXT) as page:
        await page.press("2", "}")

        assert page.cursor == (5, 0)


async def test_yank_to_next_paragraph_is_exclusive_of_blank_boundary() -> None:
    """y} yanks through the paragraph newline but not the blank boundary line."""
    async with PromptPage(TEXT) as page:
        await page.press("y", "}")

        assert page.text == TEXT
        assert page.ta._vim_register.text == "alpha\nbeta\n"
        assert page.ta._vim_register.kind == "charwise"


async def test_delete_to_next_paragraph_preserves_boundary_blank_line() -> None:
    """d} deletes up to, but not including, the next blank line."""
    async with PromptPage(TEXT) as page:
        await page.press("d", "}")

        assert page.text == "\ncharlie\n  delta\n\n\nend"
        assert page.cursor == (0, 0)


async def test_delete_to_previous_paragraph_preserves_previous_boundary() -> None:
    """d{ deletes backward from after the previous blank boundary."""
    async with PromptPage(TEXT, cursor=(4, 2)) as page:
        await page.press("d", "{")

        assert page.text == "alpha\nbeta\n\ndelta\n\n\nend"
        assert page.cursor == (3, 0)


async def test_yip_yanks_inner_paragraph_linewise() -> None:
    """yip stores the containing non-blank block as a linewise register."""
    async with PromptPage(TEXT, cursor=(4, 3)) as page:
        await page.press("y", "i", "p")

        assert page.text == TEXT
        assert page.ta._vim_register.text == "charlie\n  delta"
        assert page.ta._vim_register.kind == "linewise"


async def test_yap_yanks_paragraph_with_trailing_blank_lines() -> None:
    """yap includes trailing blank lines when they exist."""
    async with PromptPage(TEXT, cursor=(3, 1)) as page:
        await page.press("y", "a", "p")

        assert page.ta._vim_register.text == "charlie\n  delta\n\n"
        assert page.ta._vim_register.kind == "linewise"


async def test_dap_at_last_paragraph_includes_leading_blank_lines() -> None:
    """ap falls back to leading blanks when there are no trailing blanks."""
    async with PromptPage(TEXT, cursor=(7, 0)) as page:
        await page.press("d", "a", "p")

        assert page.text == "alpha\nbeta\n\ncharlie\n  delta"
        assert page.cursor == (4, 0)


async def test_dip_on_blank_line_deletes_contiguous_blank_block() -> None:
    """ip on a blank line selects the contiguous blank-line block."""
    async with PromptPage(TEXT, cursor=(5, 0)) as page:
        await page.press("d", "i", "p")

        assert page.text == "alpha\nbeta\n\ncharlie\n  delta\nend"
        assert page.cursor == (5, 0)


async def test_visual_paragraph_motion_extends_selection() -> None:
    """Visual } extends the charwise selection to the next paragraph boundary."""
    async with PromptPage(TEXT) as page:
        await page.press("v", "}", "y")

        assert page.ta._vim_register.text == "alpha\nbeta\n"
        assert page.ta._vim_register.kind == "charwise"
        assert page.mode == "normal"


async def test_vip_selects_whole_paragraph_lines() -> None:
    """vip approximates Vim by selecting whole paragraph lines."""
    async with PromptPage(TEXT, cursor=(4, 1)) as page:
        await page.press("v", "i", "p", "y")

        assert page.ta._vim_register.text == "charlie\n  delta"
        assert page.ta._vim_register.kind == "linewise"
        assert page.cursor == (3, 0)


async def test_vap_selects_paragraph_plus_trailing_blanks() -> None:
    """vap selects a paragraph and its trailing blank separator."""
    async with PromptPage(TEXT, cursor=(3, 0)) as page:
        await page.press("v", "a", "p", "y")

        assert page.ta._vim_register.text == "charlie\n  delta\n\n"
        assert page.ta._vim_register.kind == "linewise"
        assert page.cursor == (3, 0)
