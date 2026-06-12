"""Tests for PromptTextArea NORMAL-mode percent bracket motion."""

from sase.ace.testing import PromptPage


async def test_percent_jumps_from_open_to_matching_close() -> None:
    async with PromptPage("call(foo)", cursor=(0, 4)) as page:
        await page.press("%")

        assert page.cursor == (0, 8)


async def test_percent_searches_forward_on_current_line() -> None:
    async with PromptPage("call(foo)", cursor=(0, 0)) as page:
        await page.press("%")

        assert page.cursor == (0, 8)


async def test_percent_jumps_from_close_to_matching_open() -> None:
    async with PromptPage("call(foo)", cursor=(0, 8)) as page:
        await page.press("%")

        assert page.cursor == (0, 4)


async def test_percent_matches_across_lines() -> None:
    async with PromptPage("if {\n  call(x)\n}", cursor=(0, 3)) as page:
        await page.press("%")

        assert page.cursor == (2, 0)


async def test_percent_honors_nested_same_type_brackets() -> None:
    async with PromptPage("outer(inner(value))", cursor=(0, 5)) as page:
        await page.press("%")

        assert page.cursor == (0, 18)


async def test_d_percent_deletes_inclusive_range_to_match() -> None:
    async with PromptPage("a (bc) d", cursor=(0, 2)) as page:
        await page.press("d", "%")

        assert page.text == "a  d"
        assert page.cursor == (0, 2)
        assert page.ta._vim_register.text == "(bc)"


async def test_y_percent_yanks_without_modifying_text() -> None:
    async with PromptPage("a [bc] d", cursor=(0, 2)) as page:
        await page.press("y", "%")

        assert page.text == "a [bc] d"
        assert page.cursor == (0, 2)
        assert page.ta._vim_register.text == "[bc]"


async def test_percent_without_bracket_on_line_is_noop() -> None:
    async with PromptPage("abc\ndef", cursor=(0, 1)) as page:
        await page.press("%")

        assert page.cursor == (0, 1)


async def test_d_percent_without_match_clears_pending_operator() -> None:
    async with PromptPage("a (bc", cursor=(0, 2)) as page:
        await page.press("d", "%")

        assert page.text == "a (bc"
        assert page.ta._pending_operator == ""


async def test_visual_percent_extends_selection_to_match() -> None:
    async with PromptPage("a (bc) d", cursor=(0, 2)) as page:
        await page.press("v", "%", "y")

        assert page.text == "a (bc) d"
        assert page.ta._vim_register.text == "(bc)"
