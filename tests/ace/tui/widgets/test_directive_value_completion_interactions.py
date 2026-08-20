"""Tests for prompt directive-value completion UI interactions."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED

from ._completion_helpers import CompletionTestApp
from ._directive_completion_helpers import (
    MODEL_CATALOG_PATCH,
    model_entries,
    model_entries_with_providers,
)


async def test_colon_after_effort_auto_opens_directive_value_panel() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        for char in "%effort:":
            await pilot.press(char)

        assert ta.text == "%effort:"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive_arg"
        assert [c.insertion for c in ta._file_completion_candidates] == list(
            EFFORT_LEVELS_ORDERED
        )
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "directive values"
        assert "reasoning effort" in panel.render().plain


async def test_directive_arg_refresh_narrows_widens_and_dismisses() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        for char in "%effort:":
            await pilot.press(char)
        await pilot.press("h")

        assert ta.text == "%effort:h"
        assert [c.insertion for c in ta._file_completion_candidates] == ["high"]

        await pilot.press("backspace")
        assert ta.text == "%effort:"
        assert [c.insertion for c in ta._file_completion_candidates] == list(
            EFFORT_LEVELS_ORDERED
        )

        await pilot.press("space")
        assert ta.text == "%effort: "
        assert ta._file_completion_active is False


async def test_directive_arg_completion_accepts_selection() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%auto:")
        ta.cursor_location = (0, len("%auto:"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            await pilot.press("ctrl+t")
            assert ta._file_completion_active is True
            assert ta._completion_kind == "directive_arg"
            await pilot.press("down")
            selected = ta._file_completion_candidates[
                ta._file_completion_index
            ].insertion
            await pilot.press("ctrl+l")

    assert selected == "tale"
    assert ta.text == "%auto:tale"
    assert ta._file_completion_active is False


async def test_directive_arg_completion_replaces_only_partial_value() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%effort:h")
        ta.cursor_location = (0, len("%effort:h"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%effort:high"
    assert ta._file_completion_active is False


async def test_directive_arg_auto_menu_uses_directive_gate() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto_directive_menu=False),
        ):
            for char in "%auto:":
                await pilot.press(char)

        assert ta.text == "%auto:"
        assert ta._file_completion_active is False


async def test_xprompts_enabled_colon_offers_bool_values() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        for char in "%xprompts_enabled:":
            await pilot.press(char)

        assert ta._completion_kind == "directive_arg"
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == [
            "false",
            "true",
        ]


async def test_colon_after_model_auto_opens_model_value_panel() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        with patch(MODEL_CATALOG_PATCH, return_value=model_entries()):
            for char in "%model:":
                await pilot.press(char)

        assert ta.text == "%model:"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive_arg"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "claude-fable-5",
            "gpt-5.6-sol",
        ]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "%model values"
        assert "Claude" in panel.render().plain
        assert panel.border_subtitle.replace(r"\[", "[") == "[@] model aliases"


async def test_model_arg_completion_replaces_partial_with_canonical_value() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%model:fa")
        ta.cursor_location = (0, len("%model:fa"))

        with (
            patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _s: app),
            ),
            patch(MODEL_CATALOG_PATCH, return_value=model_entries()),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model:claude-fable-5"
    assert ta._file_completion_active is False


async def test_model_provider_row_acceptance_drills_down_to_scoped_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%model:cl")
        ta.cursor_location = (0, len("%model:cl"))

        with (
            patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _s: app),
            ),
            patch(MODEL_CATALOG_PATCH, return_value=model_entries_with_providers()),
        ):
            await pilot.press("ctrl+t")
            assert [c.insertion for c in ta._file_completion_candidates] == [
                "claude-fable-5",
                "claude/",
            ]
            await pilot.press("down")
            await pilot.press("ctrl+l")

    assert ta.text == "%model:claude/"
    assert ta._file_completion_active is True
    assert [c.insertion for c in ta._file_completion_candidates] == [
        "claude/claude-fable-5"
    ]


async def test_ctrl_t_unique_model_provider_row_drills_down() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%model:cod")
        ta.cursor_location = (0, len("%model:cod"))

        with (
            patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _s: app),
            ),
            patch(MODEL_CATALOG_PATCH, return_value=model_entries_with_providers()),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model:codex/"
    assert ta._file_completion_active is True
    assert [c.insertion for c in ta._file_completion_candidates] == [
        "codex/gpt-5.6-sol"
    ]


async def test_model_at_effort_completion_replaces_only_suffix() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%model:opus@xh")
        ta.cursor_location = (0, len("%model:opus@xh"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model:opus@xhigh"
    assert ta._file_completion_active is False
