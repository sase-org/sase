"""Tests for macro completion spacer behavior.

Private implementation module; import test names from the legacy facade.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.macro_arg_assist import MacroAssistEntry, MacroInputHint

from ._completion_helpers import CompletionTestApp
from ._macro_completion_spacer_helpers import input_hint, macro_entry, seed_entries


def _optional_multi_entry(name: str = "optional"):
    """Optional-only entry with a real word input plus a second optional."""
    return macro_entry(
        name,
        inputs=(
            input_hint("topic", "word", required=False),
            input_hint("count", "int", required=False, position=1),
        ),
    )


async def test_optional_multi_spacer_paren_opens_argument_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [_optional_multi_entry()])
        await pilot.press("ctrl+t")

        assert ta.text == "#optional "
        assert ta._pending_macro_completion_spacer is not None

        await pilot.press("(")

    assert ta.text == "#optional()"
    assert ta.cursor_location == (0, len("#optional("))
    assert ta._pending_macro_completion_spacer is None
    assert ta._file_completion_active is True
    assert ta._completion_kind == "macro_arg_name"
    assert [c.insertion for c in ta._file_completion_candidates] == [
        "topic=",
        "count=",
    ]


async def test_optional_multi_spacer_paren_accept_topic() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [_optional_multi_entry()])
        await pilot.press("ctrl+t")
        await pilot.press("(")

        assert ta._file_completion_active is True
        await pilot.press("ctrl+f")

    assert ta.text == "#optional(topic=)"
    assert ta.cursor_location == (0, len("#optional(topic="))
    assert ta._pending_macro_completion_spacer is None


async def test_optional_multi_spacer_paren_respects_disabled_auto_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [_optional_multi_entry()])
        await pilot.press("ctrl+t")

        assert ta._pending_macro_completion_spacer is not None
        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto_macro_menu=False),
        ):
            await pilot.press("(")

    assert ta.text == "#optional()"
    assert ta.cursor_location == (0, len("#optional("))
    assert ta._pending_macro_completion_spacer is None
    assert ta._file_completion_active is False


async def test_no_input_spacer_paren_keeps_space() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#p")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [macro_entry("plain")])
        await pilot.press("ctrl+t")

        assert ta.text == "#plain "
        assert ta._pending_macro_completion_spacer is not None

        await pilot.press("(")

    assert ta.text == "#plain ()"
    assert ta.cursor_location == (0, len("#plain ("))
    assert ta._pending_macro_completion_spacer is None


async def test_spacer_paren_preserves_prefix_and_suffix() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("before #o after")
        ta.cursor_location = (0, len("before #o"))
        seed_entries(ta, [_optional_multi_entry()])
        await pilot.press("ctrl+t")

        assert ta.text == "before #optional  after"
        await pilot.press("(")

    assert ta.text == "before #optional() after"
    assert ta._pending_macro_completion_spacer is None


async def test_spacer_paren_uses_literal_when_pairing_unsafe() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [_optional_multi_entry()])
        await pilot.press("ctrl+t")

        assert ta.text == "#optional "
        # Make pairing unsafe: a word character follows the spacer.
        ta._replace_absolute_range(len(ta.text), len(ta.text), "x")
        assert ta.text == "#optional x"
        # Cursor is no longer immediately after the spacer, so the owned
        # rewrite is stale; ordinary pairing inserts a literal "(".
        await pilot.press("(")

    assert ta.text == "#optional x()"
    assert ta._pending_macro_completion_spacer is None


async def test_spacer_paren_selection_and_normal_mode_keep_space() -> None:
    from textual.widgets.text_area import Selection

    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [_optional_multi_entry()])
        await pilot.press("ctrl+t")

        assert ta._pending_macro_completion_spacer is not None
        ta.selection = Selection((0, 0), (0, 1))
        await pilot.press("(")

    assert ta.text != "#optional()"
    assert ta.text != "#optional "
    assert ta._pending_macro_completion_spacer is None


async def test_spacer_paren_is_one_undo_step() -> None:
    from sase.ace.testing import PromptPage

    async with PromptPage(
        "#optional ",
        cursor=(0, len("#optional ")),
        mode="insert",
    ) as page:
        ta = page.ta
        seed_entries(ta, [_optional_multi_entry()])
        # Simulate an accepted completion that owns the trailing space.
        from sase.ace.tui.widgets.macro_arg_assist import (
            PendingMacroCompletionSpacer,
        )

        ta._pending_macro_completion_spacer = PendingMacroCompletionSpacer(
            spacer_offset=len("#optional"),
            reference_start=0,
            reference_text="#optional",
            has_optional_inputs=True,
        )
        await page.press("(")
        assert page.text == "#optional()"

        await page.press("escape", "u")

        assert page.text == "#optional "


async def test_manual_lookalike_space_is_preserved_on_paren() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        seed_entries(ta, [_optional_multi_entry()])
        ta.load_text("#optional ")
        ta.cursor_location = (0, len("#optional "))

        assert ta._pending_macro_completion_spacer is None
        await pilot.press("(")

    assert ta.text == "#optional ()"
    assert ta._pending_macro_completion_spacer is None
