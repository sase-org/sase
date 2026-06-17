"""Regression tests confirming NORMAL-mode ``J`` no longer joins lines.

Vim normal-mode ``J`` (join lines) was intentionally retired when the prompt
text area rebound normal-mode ``J`` / ``K`` to prompt-stack pane focus.  A bare
``J`` in a single prompt (no multi-pane stack to focus) is swallowed as a no-op
rather than joining lines, so it never leaks to the app-level Agents-tab
``J`` / ``K`` panel-focus bindings either.
"""

from sase.ace.testing import PromptPage


async def test_J_no_longer_joins_two_lines() -> None:
    """``J`` leaves multiline text untouched (the join command is retired)."""
    async with PromptPage("hello\nworld") as page:
        await page.press("J")
        assert page.text == "hello\nworld"
        # The cursor never moves to a join point because nothing was joined.
        assert page.cursor == (0, 0)


async def test_J_with_count_no_longer_joins() -> None:
    """A counted ``3J`` no longer joins lines either."""
    async with PromptPage("one\ntwo\nthree\nfour") as page:
        await page.press("3", "J")
        assert page.text == "one\ntwo\nthree\nfour"


async def test_dot_does_not_repeat_a_join() -> None:
    """With ``J`` retired, ``.`` has no join mutation to replay."""
    async with PromptPage("aaa\nbbb\nccc") as page:
        await page.press("J")
        await page.press(".")
        assert page.text == "aaa\nbbb\nccc"
