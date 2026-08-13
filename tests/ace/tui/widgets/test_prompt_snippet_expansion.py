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

    def get_snippets(self) -> dict[str, str]:
        return self._snippets

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

    async def test_tab_dispatch_expands_trigger_later_on_bullet_line(self) -> None:
        """Bullet shifting does not take over Tab once inside item content."""
        app = _SnippetTestApp({"snip": "EXPANDED"})
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
        ta, expanded = await _setup(
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
        ta, expanded = await _setup(
            snippets={"foo": "(\n  foo\n  bar\n)"},
            text="  foo",
            cursor=(0, 5),
        )
        assert expanded is True
        assert ta.text == "  (\n    foo\n    bar\n  )"

    async def test_no_indent_at_column_zero(self) -> None:
        """No extra indentation when trigger line has no leading whitespace."""
        ta, expanded = await _setup(
            snippets={"foo": "(\n  foo\n)"},
            text="foo",
            cursor=(0, 3),
        )
        assert expanded is True
        assert ta.text == "(\n  foo\n)"

    async def test_indented_with_preceding_lines(self) -> None:
        """Indentation works when trigger is on a later line."""
        ta, expanded = await _setup(
            snippets={"foo": "(\n  foo\n  bar\n)"},
            text="prefix\n\n  foo",
            cursor=(2, 5),
        )
        assert expanded is True
        assert ta.text == "prefix\n\n  (\n    foo\n    bar\n  )"

    async def test_tabstop_on_indented_continuation(self) -> None:
        """Tabstop on a continuation line accounts for added indentation."""
        app = _SnippetTestApp({"blk": "{\n  $1\n}"})
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
        app = _SnippetTestApp({"blk": "{\n  $1\n}$0"})
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


class TestSnippetPriority:
    async def test_expand_snippet_takes_priority_over_tabstop(self) -> None:
        """Typing a trigger at an active tabstop nests instead of destroying it."""
        app = _SnippetTestApp({"wrap": "($1)$0", "inner": "INNER"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("wrap")
            ta.cursor_location = (0, 4)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            # Now at $1 inside "()" with $0 still pending
            assert ta.text == "()"
            assert ta.cursor_location == (0, 1)
            assert ta.snippet_session_active is True

            # Type a second trigger word at the $1 position through the
            # real edit funnel (not load_text, which bypasses it and would
            # never reach the session).
            ta._replace_via_keyboard("inner", (0, 1), (0, 1))
            assert ta.text == "(inner)"
            assert ta.cursor_location == (0, 6)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                expanded = ta._try_expand_snippet()
            assert expanded is True
            assert ta.text == "(INNER)"
            # The outer $0 survives the nested (marker-less) expansion.
            assert ta.snippet_session_active is True
            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location == (0, 7)
            # $0 was the outer session's last stop: advancing past it ends
            # the session.
            assert ta.snippet_session_active is True
            assert ta._try_advance_tabstop() is False
            assert ta.snippet_session_active is False


class TestNestedSessions:
    async def test_nesting_at_a_stop_resumes_outer_session_after_inner_exhausts(
        self,
    ) -> None:
        """The reported bug: nesting a snippet at a live tabstop must not
        destroy the enclosing snippet's remaining stops.
        """
        app = _SnippetTestApp(
            {
                "outer": "foo $1 bar $2 baz $3 buz",
                "inner": "inner $1 done",
            }
        )
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("outer")
            ta.cursor_location = (0, 5)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "foo  bar  baz  buz"
            assert ta.cursor_location == (0, 4)
            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location == (0, 9)

            # Type "inner" at the outer $2 stop through the real edit
            # funnel so the session sees each character's delta.
            ta._replace_via_keyboard("inner", (0, 9), (0, 9))
            assert ta.cursor_location == (0, 14)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "foo  bar inner  done baz  buz"

            # Inner's own $1, then inner's own implicit $0.
            assert ta._try_advance_tabstop() is True
            inner_zero = ta.cursor_location
            # Exhausting inner resumes the outer session at $3, not the
            # end of a discarded one.
            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location != inner_zero
            assert ta.text[ta._absolute_offset(ta.cursor_location) :].startswith(" buz")
            assert ta.snippet_session_active is True

            # And the outer $0 still follows.
            assert ta._try_advance_tabstop() is True
            assert ta.text[ta._absolute_offset(ta.cursor_location) :] == ""
            assert ta.snippet_session_active is True

            # $0 was the last stop: advancing past it ends the session.
            assert ta._try_advance_tabstop() is False
            assert ta.snippet_session_active is False


class TestTabstopExpansion:
    async def test_dollar_one_places_cursor(self) -> None:
        """$1 places cursor at first tabstop on expansion."""
        ta, expanded = await _setup(
            snippets={"fi": "the $1 file"},
            text="fi",
            cursor=(0, 2),
        )
        assert expanded is True
        assert ta.text == "the  file"
        assert ta.cursor_location == (0, 4)

    async def test_escaped_dollar_is_literal_text(self) -> None:
        """Escaped dollars are not treated as tabstop markers."""
        ta, expanded = await _setup(
            snippets={"cash": r"Cost \$1 then $1$0"},
            text="cash",
            cursor=(0, 4),
        )
        assert expanded is True
        assert ta.text == "Cost $1 then "
        assert ta.cursor_location == (0, 13)

    async def test_advance_to_implicit_end(self) -> None:
        """Tab advances to end of expansion when no $0 present."""
        app = _SnippetTestApp({"fi": "the $1 file"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("fi")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.cursor_location == (0, 4)
            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location == (0, 9)

    async def test_advance_to_explicit_dollar_zero(self) -> None:
        """Tab advances from $1 to explicit $0 position."""
        app = _SnippetTestApp({"wrap": "($1)$0"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("wrap")
            ta.cursor_location = (0, 4)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "()"
            assert ta.cursor_location == (0, 1)
            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location == (0, 2)

    async def test_multiple_tabstops_in_order(self) -> None:
        """$1 then $2 then $0 visited in order."""
        app = _SnippetTestApp({"fn": "def $1($2):$0"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("fn")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "def ():"
            assert ta.cursor_location == (0, 4)
            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location == (0, 5)
            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location == (0, 7)

    async def test_no_advance_without_active_session(self) -> None:
        """_try_advance_tabstop returns False when no session active."""
        ta, expanded = await _setup(
            snippets={"hello": "Hello World"},
            text="hello",
            cursor=(0, 5),
        )
        assert expanded is True
        assert ta._try_advance_tabstop() is False

    async def test_advance_with_trailing_text(self) -> None:
        """Tabstop positions adjust correctly with text after expansion."""
        app = _SnippetTestApp({"fi": "the $1 file"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("fi done")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "the  file done"
            assert ta.cursor_location == (0, 4)
            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location == (0, 9)

    async def test_advance_after_typing(self) -> None:
        """Tabstop end position adjusts for text typed at earlier tabstop."""
        app = _SnippetTestApp({"fi": "the $1 file"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("fi")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.cursor_location == (0, 4)
            # Type "main" at $1 through the real edit funnel (not
            # load_text, which bypasses it and would never reach the
            # session).
            ta._replace_via_keyboard("main", (0, 4), (0, 4))
            assert ta.text == "the main file"
            assert ta.cursor_location == (0, 8)
            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location == (0, 13)


class TestBackwardTabstopNavigation:
    async def test_shift_tab_dispatch_retreats_through_key_handling(self) -> None:
        """Shift+Tab through the real key-handling path retreats a live session."""
        app = _SnippetTestApp({"fn": "def $1($2):$0"})
        async with app.run_test() as pilot:
            ta = app.query_one(PromptTextArea)
            ta.load_text("fn")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _self: app),
            ):
                await pilot.press("tab")
            assert ta.text == "def ():"
            assert ta.cursor_location == (0, 4)
            await pilot.press("tab")
            assert ta.cursor_location == (0, 5)

            await pilot.press("shift+tab")
            assert ta.cursor_location == (0, 4)
            assert ta.snippet_session_active is True

    async def test_retreat_lands_at_end_of_typed_text(self) -> None:
        """Retreat to an earlier stop lands at the end of what was typed there,
        per sticky-right anchoring.
        """
        app = _SnippetTestApp({"fn": "def $1($2):$0"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("fn")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.cursor_location == (0, 4)
            # Type "main" at $1 through the real edit funnel.
            ta._replace_via_keyboard("main", (0, 4), (0, 4))
            assert ta.text == "def main():"
            assert ta.cursor_location == (0, 8)

            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location == (0, 9)

            assert ta._try_retreat_tabstop() is True
            # Lands at the end of "main", not in front of it.
            assert ta.cursor_location == (0, 8)
            assert ta.snippet_session_active is True

    async def test_retreat_crosses_nesting_boundary(self) -> None:
        """Retreating from an inner snippet's first stop lands on the outer
        stop that was nested into, remapped by the inner expansion's own
        edit (sticky-right, same as test_retreat_lands_at_end_of_typed_text),
        and a following advance returns forward into the inner stops.
        """
        app = _SnippetTestApp(
            {
                "outer": "foo $1 bar $2 baz $3 buz",
                "inner": "inner $1 done",
            }
        )
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("outer")
            ta.cursor_location = (0, 5)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "foo  bar  baz  buz"
            assert ta.cursor_location == (0, 4)
            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location == (0, 9)

            ta._replace_via_keyboard("inner", (0, 9), (0, 9))
            # Typing at the stop pushes it forward with what was typed
            # (sticky-right), so it now sits at the end of "inner".
            assert ta.cursor_location == (0, 14)
            text_before_inner_expand = ta.text
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.text == "foo  bar inner  done baz  buz"
            inner_expand_delta = len(ta.text) - len(text_before_inner_expand)
            # The outer stop sat exactly at the inner expansion's edit
            # boundary, so it shifts by that same sticky-right delta.
            outer_stop_after_nesting = (0, 14 + inner_expand_delta)

            # Retreating from the inner snippet's first (and only) stop
            # resumes the outer session at the stop that was nested into.
            assert ta._try_retreat_tabstop() is True
            assert ta.cursor_location == outer_stop_after_nesting

            # A following advance returns forward into the inner stops.
            assert ta._try_advance_tabstop() is True
            assert ta.cursor_location != outer_stop_after_nesting
            assert ta.snippet_session_active is True

    async def test_retreat_at_first_stop_is_a_no_op(self) -> None:
        """Shift+Tab at the first stop stays a consumed no-op."""
        app = _SnippetTestApp({"fn": "def $1($2):$0"})
        async with app.run_test():
            ta = app.query_one(PromptTextArea)
            ta.load_text("fn")
            ta.cursor_location = (0, 2)
            with patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda s: app),
            ):
                assert ta._try_expand_snippet() is True
            assert ta.cursor_location == (0, 4)
            assert ta._try_retreat_tabstop() is False
            assert ta.cursor_location == (0, 4)
            assert ta.snippet_session_active is True

    async def test_no_retreat_without_active_session(self) -> None:
        """_try_retreat_tabstop returns False when no session is active."""
        ta, expanded = await _setup(
            snippets={"hello": "Hello World"},
            text="hello",
            cursor=(0, 5),
        )
        assert expanded is True
        assert ta._try_retreat_tabstop() is False
