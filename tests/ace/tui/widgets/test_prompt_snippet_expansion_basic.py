"""Basic prompt snippet-expansion tests.

Split from ``test_prompt_snippet_expansion``; shared helpers live in
``_prompt_snippet_expansion_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._prompt_snippet_expansion_shared import (
    SnippetTestApp,
    setup_snippet_expansion,
)


class TestBasicExpansion:
    async def test_trigger_expands_with_cursor_at_marker(self) -> None:
        """Trigger word expands, cursor placed at $0."""
        ta, expanded = await setup_snippet_expansion(
            snippets={"foobar": "A lot of foo with a $0 of bar."},
            text="foobar",
            cursor=(0, 6),
        )
        assert expanded is True
        assert ta.text == "A lot of foo with a  of bar."
        assert ta.cursor_location == (0, 20)

    async def test_cursor_at_end_when_no_marker(self) -> None:
        """Template without $0 leaves cursor at end of expansion."""
        ta, expanded = await setup_snippet_expansion(
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
        ta, expanded = await setup_snippet_expansion(
            snippets={"foobar": "expanded"},
            text="unknown",
            cursor=(0, 7),
        )
        assert expanded is False
        assert ta.text == "unknown"

    async def test_no_word_before_cursor(self) -> None:
        """Cursor at start of line returns False."""
        ta, expanded = await setup_snippet_expansion(
            snippets={"foobar": "expanded"},
            text="foobar",
            cursor=(0, 0),
        )
        assert expanded is False
        assert ta.text == "foobar"

    async def test_cursor_after_space(self) -> None:
        """Cursor right after a space returns False (no word)."""
        ta, expanded = await setup_snippet_expansion(
            snippets={"foobar": "expanded"},
            text="foobar ",
            cursor=(0, 7),
        )
        assert expanded is False


class TestTriggerInContext:
    async def test_trigger_in_middle_of_line(self) -> None:
        """Text before and after trigger is preserved."""
        ta, expanded = await setup_snippet_expansion(
            snippets={"snip": "EXPANDED$0"},
            text="prefix snip suffix",
            cursor=(0, 11),
        )
        assert expanded is True
        assert ta.text == "prefix EXPANDED suffix"
        assert ta.cursor_location == (0, 15)

    async def test_underscore_in_trigger(self) -> None:
        """Underscores are part of the trigger word."""
        ta, expanded = await setup_snippet_expansion(
            snippets={"my_snippet": "replaced"},
            text="my_snippet",
            cursor=(0, 10),
        )
        assert expanded is True
        assert ta.text == "replaced"

    async def test_tab_dispatch_expands_trigger_later_on_bullet_line(self) -> None:
        """Bullet shifting does not take over Tab once inside item content."""
        app = SnippetTestApp({"snip": "EXPANDED"})
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("- snip")
            ta.cursor_location = (0, 6)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _self: app),
            ):
                await pilot.press("tab")

            assert ta.text == "- EXPANDED"
            assert ta.cursor_location == (0, 10)


class TestMultiLineExpansion:
    async def test_cursor_on_second_line(self) -> None:
        """$0 on second line of expansion computes correct row/col."""
        ta, expanded = await setup_snippet_expansion(
            snippets={"blk": "line one\nline $0two"},
            text="blk",
            cursor=(0, 3),
        )
        assert expanded is True
        assert ta.text == "line one\nline two"
        assert ta.cursor_location == (1, 5)


class TestMultiLineIndentation:
    async def test_continuation_lines_indented(self) -> None:
        """Multi-line expansion indents continuation lines to match trigger."""
        ta, expanded = await setup_snippet_expansion(
            snippets={"foo": "(\n  foo\n  bar\n)"},
            text="  foo",
            cursor=(0, 5),
        )
        assert expanded is True
        assert ta.text == "  (\n    foo\n    bar\n  )"

    async def test_no_indent_at_column_zero(self) -> None:
        """No extra indentation when trigger line has no leading whitespace."""
        ta, expanded = await setup_snippet_expansion(
            snippets={"foo": "(\n  foo\n)"},
            text="foo",
            cursor=(0, 3),
        )
        assert expanded is True
        assert ta.text == "(\n  foo\n)"

    async def test_indented_with_preceding_lines(self) -> None:
        """Indentation works when trigger is on a later line."""
        ta, expanded = await setup_snippet_expansion(
            snippets={"foo": "(\n  foo\n  bar\n)"},
            text="prefix\n\n  foo",
            cursor=(2, 5),
        )
        assert expanded is True
        assert ta.text == "prefix\n\n  (\n    foo\n    bar\n  )"

    async def test_tabstop_on_indented_continuation(self) -> None:
        """Tabstop on a continuation line accounts for added indentation."""
        app = SnippetTestApp({"blk": "{\n  $1\n}"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("    blk")
            ta.cursor_location = (0, 7)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "    {\n      \n    }"
            assert ta.cursor_location == (1, 6)

    async def test_advance_tabstop_on_indented_expansion(self) -> None:
        """Tab advances correctly in indented multi-line expansion."""
        app = SnippetTestApp({"blk": "{\n  $1\n}$0"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("    blk")
            ta.cursor_location = (0, 7)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "    {\n      \n    }"
            assert ta.cursor_location == (1, 6)
            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location == (2, 5)
