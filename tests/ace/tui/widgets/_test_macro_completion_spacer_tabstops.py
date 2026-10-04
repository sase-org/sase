"""Tests for macro completion spacer behavior.

Private implementation module; import test names from the legacy facade.
"""

from __future__ import annotations

from unittest.mock import patch

from textual.pilot import Pilot

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp
from ._macro_completion_spacer_helpers import macro_entry, seed_entries


async def _seed_double_tabstop_completion(
    pilot: Pilot[None],
    ta: PromptTextArea,
) -> None:
    """Expand ``$1 and $0``, insert ``#p``, accept ``#plain`` at ``$1``.

    Builds the session without ``load_text`` (which clears it): the template
    expands directly, then the trigger is inserted through the widget's own
    edit path so the tabstops remap the same way they do in the app. Leaves
    ``"#plain  and "`` with the cursor at (0, 7) and a pending spacer at
    offset 6.
    """
    ta.load_text("")
    ta._expand_snippet_template_at_range(
        "$1 and $0", (0, 0), (0, 0), session_policy="reset"
    )
    ta._replace_via_keyboard("#p", (0, 0), (0, 0))
    seed_entries(ta, [macro_entry("plain")])
    await pilot.press("ctrl+t")


async def test_tab_after_spacer_jumps_to_next_tabstop_without_the_space() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await _seed_double_tabstop_completion(pilot, ta)

        assert ta.text == "#plain  and "
        assert ta.cursor_location == (0, 7)

        await pilot.press("tab")

    assert ta.text == "#plain and "
    assert ta.cursor_location == (0, 11)
    assert ta._pending_macro_completion_spacer is None


async def test_shift_tab_after_spacer_retreats_without_the_space() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("")
        ta._expand_snippet_template_at_range(
            "$1 and $0", (0, 0), (0, 0), session_policy="reset"
        )
        await pilot.press("tab")
        ta._replace_via_keyboard("#p", ta.cursor_location, ta.cursor_location)
        seed_entries(ta, [macro_entry("plain")])
        await pilot.press("ctrl+t")

        assert ta.text == " and #plain "
        assert ta._pending_macro_completion_spacer is not None

        await pilot.press("shift+tab")

    assert ta.text == " and #plain"
    assert ta.cursor_location == (0, 0)
    assert ta._pending_macro_completion_spacer is None


async def test_tab_without_a_snippet_session_keeps_the_spacer() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#p")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [macro_entry("plain")])
        await pilot.press("ctrl+t")

        assert ta.text == "#plain "
        assert ta._pending_macro_completion_spacer is not None

        await pilot.press("tab")

    assert ta.text == "#plain "


async def test_tab_at_the_last_tabstop_keeps_the_spacer() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("")
        ta._expand_snippet_template_at_range(
            "only $0", (0, 0), (0, 0), session_policy="reset"
        )
        ta._replace_via_keyboard("#p", ta.cursor_location, ta.cursor_location)
        seed_entries(ta, [macro_entry("plain")])
        await pilot.press("ctrl+t")

        assert ta.text == "only #plain "
        assert ta._pending_macro_completion_spacer is not None

        await pilot.press("tab")

    assert ta.text == "only #plain "
    assert ta.snippet_session_active is False


async def test_tab_does_not_expand_a_snippet_named_after_the_macro() -> None:
    app = CompletionTestApp(snippets={"plain": "EXPANDED"})
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await _seed_double_tabstop_completion(pilot, ta)

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _self: app),
        ):
            await pilot.press("tab")

    assert ta.text == "#plain and "
    assert "EXPANDED" not in ta.text


async def test_cursor_movement_invalidates_the_tab_spacer_deletion() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await _seed_double_tabstop_completion(pilot, ta)

        # One column past the spacer, still preceded by a space so the
        # fallback ``tab`` path finds no snippet-trigger word to expand.
        ta.cursor_location = (0, 8)
        await pilot.press("tab")

    assert ta.text == "#plain  and "


async def test_spacer_tab_deletion_is_one_shot() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await _seed_double_tabstop_completion(pilot, ta)

        await pilot.press("tab")
        assert ta.text == "#plain and "
        assert ta.cursor_location == (0, 11)

        await pilot.press("tab")

    assert ta.text == "#plain and "
    assert ta.snippet_session_active is False
