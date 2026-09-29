"""Nested snippet-session tests.

Split from ``test_prompt_snippet_expansion``; shared helpers live in
``_prompt_snippet_expansion_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._prompt_snippet_expansion_shared import SnippetTestApp


class TestSnippetPriority:
    async def test_expand_snippet_takes_priority_over_tabstop(self) -> None:
        """Typing a trigger at an active tabstop nests instead of destroying it."""
        app = SnippetTestApp({"wrap": "($1)$0", "inner": "INNER"})
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
