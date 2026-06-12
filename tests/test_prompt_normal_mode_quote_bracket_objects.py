"""Tests for PromptTextArea NORMAL-mode quote and bracket text objects."""

from sase.ace.testing import PromptPage


async def test_ci_double_quote_changes_inside_quotes() -> None:
    async with PromptPage('foo "bar baz" qux', cursor=(0, 6)) as page:
        await page.press("c", "i", '"')

        assert page.mode == "insert"
        assert page.text == 'foo "" qux'
        assert page.cursor == (0, 5)


async def test_da_double_quote_includes_quotes_and_trailing_space() -> None:
    async with PromptPage('foo "bar" baz', cursor=(0, 6)) as page:
        await page.press("d", "a", '"')

        assert page.text == "foo baz"
        assert page.cursor == (0, 4)
        assert page.ta._vim_register.text == '"bar" '


async def test_da_double_quote_includes_leading_space_at_line_end() -> None:
    async with PromptPage('foo "bar"', cursor=(0, 6)) as page:
        await page.press("d", "a", '"')

        assert page.text == "foo"
        assert page.ta._vim_register.text == ' "bar"'


async def test_yi_single_quote_searches_forward_on_line() -> None:
    async with PromptPage("prefix 'value' suffix") as page:
        await page.press("y", "i", "'")

        assert page.text == "prefix 'value' suffix"
        assert page.cursor == (0, 8)
        assert page.ta._vim_register.text == "value"
        assert page.ta._vim_register.kind == "charwise"


async def test_ci_backtick_changes_inside_backticks() -> None:
    async with PromptPage("run `sase ace` now", cursor=(0, 6)) as page:
        await page.press("c", "i", "`")

        assert page.mode == "insert"
        assert page.text == "run `` now"


async def test_di_quote_without_match_is_noop_and_clears_operator() -> None:
    async with PromptPage("no quotes here") as page:
        await page.press("d", "i", '"')

        assert page.text == "no quotes here"
        assert page.ta._pending_operator == ""


async def test_ci_parenthesis_uses_innermost_nested_pair() -> None:
    async with PromptPage("call(foo(bar), baz)", cursor=(0, 9)) as page:
        await page.press("c", "i", "(")

        assert page.mode == "insert"
        assert page.text == "call(foo(), baz)"
        assert page.cursor == (0, 9)


async def test_da_parenthesis_deletes_innermost_pair() -> None:
    async with PromptPage("call(foo(bar), baz)", cursor=(0, 9)) as page:
        await page.press("d", "a", "(")

        assert page.text == "call(foo, baz)"
        assert page.ta._vim_register.text == "(bar)"


async def test_yib_uses_parenthesis_alias() -> None:
    async with PromptPage("call(value)", cursor=(0, 6)) as page:
        await page.press("y", "i", "b")

        assert page.ta._vim_register.text == "value"
        assert page.ta._vim_register.kind == "charwise"


async def test_di_brace_spans_multiple_lines() -> None:
    async with PromptPage("if {\n  one\n  two\n}\nend", cursor=(1, 2)) as page:
        await page.press("d", "i", "{")

        assert page.text == "if {}\nend"
        assert page.ta._vim_register.text == "\n  one\n  two\n"


async def test_yaB_uses_brace_alias() -> None:
    async with PromptPage("wrap {value} tail", cursor=(0, 7)) as page:
        await page.press("y", "a", "B")

        assert page.ta._vim_register.text == "{value}"


async def test_ci_square_brackets() -> None:
    async with PromptPage("items[alpha, beta]", cursor=(0, 7)) as page:
        await page.press("c", "i", "[")

        assert page.mode == "insert"
        assert page.text == "items[]"


async def test_di_angle_brackets() -> None:
    async with PromptPage("tag <inner> done", cursor=(0, 6)) as page:
        await page.press("d", "i", "<")

        assert page.text == "tag <> done"
