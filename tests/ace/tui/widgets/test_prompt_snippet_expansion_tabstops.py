"""Tabstop navigation tests for prompt snippet expansion.

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


class TestTabstopExpansion:
    async def test_dollar_one_places_cursor(self) -> None:
        """$1 places cursor at first tabstop on expansion."""
        ta, expanded = await setup_snippet_expansion(
            snippets={"fi": "the $1 file"},
            text="fi",
            cursor=(0, 2),
        )
        assert expanded is True
        assert ta.text == "the  file"
        assert ta.cursor_location == (0, 4)

    async def test_escaped_dollar_is_literal_text(self) -> None:
        """Escaped dollars are not treated as tabstop markers."""
        ta, expanded = await setup_snippet_expansion(
            snippets={"cash": r"Cost \$1 then $1$0"},
            text="cash",
            cursor=(0, 4),
        )
        assert expanded is True
        assert ta.text == "Cost $1 then "
        assert ta.cursor_location == (0, 13)

    async def test_advance_to_implicit_end(self) -> None:
        """Tab advances to end of expansion when no $0 present."""
        app = SnippetTestApp({"fi": "the $1 file"})
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
        app = SnippetTestApp({"wrap": "($1)$0"})
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
        app = SnippetTestApp({"fn": "def $1($2):$0"})
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
        ta, expanded = await setup_snippet_expansion(
            snippets={"hello": "Hello World"},
            text="hello",
            cursor=(0, 5),
        )
        assert expanded is True
        assert ta._try_advance_tabstop() is False

    async def test_advance_with_trailing_text(self) -> None:
        """Tabstop positions adjust correctly with text after expansion."""
        app = SnippetTestApp({"fi": "the $1 file"})
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
        app = SnippetTestApp({"fi": "the $1 file"})
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
        app = SnippetTestApp({"fn": "def $1($2):$0"})
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
        app = SnippetTestApp({"fn": "def $1($2):$0"})
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
        app = SnippetTestApp(
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
        app = SnippetTestApp({"fn": "def $1($2):$0"})
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
        ta, expanded = await setup_snippet_expansion(
            snippets={"hello": "Hello World"},
            text="hello",
            cursor=(0, 5),
        )
        assert expanded is True
        assert ta._try_retreat_tabstop() is False

    async def test_no_retreat_after_the_session_ends(self) -> None:
        """Advancing off the last stop clears the session, so backward
        navigation is not available afterwards.
        """
        app = SnippetTestApp({"fn": "def $1($2):$0"})
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

            # Walk to the last stop ($0), then off it.
            assert ta._try_advance_tabstop() is True
            assert ta._try_advance_tabstop() is True
            assert ta.snippet_session_active is True
            assert ta._try_advance_tabstop() is False
            assert ta.snippet_session_active is False

            ended_at = ta.cursor_location
            assert ta._try_retreat_tabstop() is False
            assert ta.cursor_location == ended_at
