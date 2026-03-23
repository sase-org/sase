"""Tests for prompt input snippet expansion."""

from __future__ import annotations

from unittest.mock import patch

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class _SnippetTestApp(App):
    """Minimal app that hosts a PromptTextArea for snippet testing."""

    def __init__(self, snippets: dict[str, str] | None = None) -> None:
        super().__init__()
        self._snippets: dict[str, str] = snippets or {}

    def compose(self) -> ComposeResult:
        yield PromptTextArea()


async def _setup(
    snippets: dict[str, str],
    text: str = "",
    cursor: tuple[int, int] = (0, 0),
) -> tuple[PromptTextArea, bool]:
    """Mount a PromptTextArea with text/cursor and try to expand a snippet.

    Returns (widget, expanded) so tests can assert on both the result
    and the resulting text/cursor state.
    """
    app = _SnippetTestApp(snippets)
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        if text:
            ta.load_text(text)
        ta.cursor_location = cursor
        with patch.object(
            type(ta), "_ace_app", new_callable=lambda: property(lambda self: app)
        ):
            result = ta._try_expand_snippet()
        return ta, result


class TestBasicExpansion:
    async def test_trigger_expands_with_cursor_at_marker(self) -> None:
        """Trigger word expands, cursor placed at $0."""
        ta, expanded = await _setup(
            snippets={"foobar": "A lot of foo with a $0 of bar."},
            text="foobar",
            cursor=(0, 6),
        )
        assert expanded is True
        assert ta.text == "A lot of foo with a  of bar."
        assert ta.cursor_location == (0, 20)

    async def test_cursor_at_end_when_no_marker(self) -> None:
        """Template without $0 leaves cursor at end of expansion."""
        ta, expanded = await _setup(
            snippets={"hello": "Hello World"},
            text="hello",
            cursor=(0, 5),
        )
        assert expanded is True
        assert ta.text == "Hello World"
        # No $0 → cursor stays at end (default _replace_via_keyboard behavior)


class TestNoExpansion:
    async def test_no_match_returns_false(self) -> None:
        """Unknown trigger returns False and text is unchanged."""
        ta, expanded = await _setup(
            snippets={"foobar": "expanded"},
            text="unknown",
            cursor=(0, 7),
        )
        assert expanded is False
        assert ta.text == "unknown"

    async def test_no_word_before_cursor(self) -> None:
        """Cursor at start of line returns False."""
        ta, expanded = await _setup(
            snippets={"foobar": "expanded"},
            text="foobar",
            cursor=(0, 0),
        )
        assert expanded is False
        assert ta.text == "foobar"

    async def test_cursor_after_space(self) -> None:
        """Cursor right after a space returns False (no word)."""
        ta, expanded = await _setup(
            snippets={"foobar": "expanded"},
            text="foobar ",
            cursor=(0, 7),
        )
        assert expanded is False


class TestTriggerInContext:
    async def test_trigger_in_middle_of_line(self) -> None:
        """Text before and after trigger is preserved."""
        ta, expanded = await _setup(
            snippets={"snip": "EXPANDED$0"},
            text="prefix snip suffix",
            cursor=(0, 11),
        )
        assert expanded is True
        assert ta.text == "prefix EXPANDED suffix"
        assert ta.cursor_location == (0, 15)

    async def test_underscore_in_trigger(self) -> None:
        """Underscores are part of the trigger word."""
        ta, expanded = await _setup(
            snippets={"my_snippet": "replaced"},
            text="my_snippet",
            cursor=(0, 10),
        )
        assert expanded is True
        assert ta.text == "replaced"


class TestMultiLineExpansion:
    async def test_cursor_on_second_line(self) -> None:
        """$0 on second line of expansion computes correct row/col."""
        ta, expanded = await _setup(
            snippets={"blk": "line one\nline $0two"},
            text="blk",
            cursor=(0, 3),
        )
        assert expanded is True
        assert ta.text == "line one\nline two"
        assert ta.cursor_location == (1, 5)
