"""Interaction tests for ``==model`` prompt model completion.

Split from ``test_model_explicit_completion``; shared helpers live in
``_model_explicit_completion_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.widgets.model_alias_completion import MODEL_ALIAS_COMPLETION_KIND
from sase.ace.tui.widgets.model_explicit_completion import (
    MODEL_EXPLICIT_COMPLETION_KIND,
    MODEL_EXPLICIT_MODE_SUBTITLE,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._model_explicit_completion_shared import (
    ModelExplicitCompletionTestApp,
    explicit_entries,
)

__all__ = [
    "test_double_equals_accept_preserves_context_and_undo_redo",
    "test_double_equals_accept_replaces_whole_token_from_mid_token_cursor",
    "test_double_equals_auto_opens_and_ctrl_e_expands_without_submit",
    "test_double_equals_ctrl_l_accepts_selection_without_submit_or_newline",
    "test_double_equals_ctrl_t_opens_when_auto_directive_menu_disabled",
    "test_double_equals_enter_submits_unexpanded_text_while_menu_is_open",
    "test_double_equals_navigation_preserves_selection_while_filtering",
    "test_double_equals_third_equals_and_space_dismiss_completion",
    "test_equals_shortcut_switches_between_alias_and_model_in_manual_session",
    "test_second_equals_takes_over_when_alias_catalog_is_loading",
    "test_second_equals_takes_over_when_alias_rows_are_empty",
    "test_warm_double_equals_typing_never_builds_catalog_on_key_path",
]


def _candidate_insertions(text_area: PromptTextArea) -> list[str]:
    return [candidate.insertion for candidate in text_area._file_completion_candidates]


def _selected_insertion(text_area: PromptTextArea) -> str:
    return text_area._file_completion_candidates[
        text_area._file_completion_index
    ].insertion


async def test_double_equals_auto_opens_and_ctrl_e_expands_without_submit() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()

        await pilot.press("=")
        assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND

        await pilot.press("=")
        await pilot.press("g")

        panel = bar.query_one("#prompt-completion", Static)
        assert ta._file_completion_active is True
        assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND
        assert panel.border_title == "explicit models"
        assert _candidate_insertions(ta) == ["gpt-5.6-sol"]
        assert "Ctrl+F → %m:gpt-5.6-sol · Codex (sol)" in str(panel.border_subtitle)
        assert bar._subtitle_base == MODEL_EXPLICIT_MODE_SUBTITLE

        await pilot.press("ctrl+f")

        assert ta.text == "%m:gpt-5.6-sol "
        assert app.submitted == []
        assert ta._file_completion_active is False
        assert ta._insert_g_prefix_pending is False
        assert bar._subtitle_base == bar._mode_subtitle


async def test_double_equals_enter_submits_unexpanded_text_while_menu_is_open() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        await pilot.press("=")
        await pilot.press("g")
        assert ta._file_completion_active is True

        await pilot.press("enter")

        assert ta.text == "==g"
        assert app.submitted == ["==g"]
        assert ta._file_completion_active is False


async def test_double_equals_ctrl_t_opens_when_auto_directive_menu_disabled() -> None:
    app = ModelExplicitCompletionTestApp(
        settings=PromptCompletionSettings(auto_directive_menu=False, next_word="chain"),
    )
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        await pilot.press("=")
        await pilot.press("g")
        assert ta._file_completion_active is False

        await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND
        assert _candidate_insertions(ta) == ["gpt-5.6-sol"]


async def test_equals_shortcut_switches_between_alias_and_model_in_manual_session() -> (
    None
):
    app = ModelExplicitCompletionTestApp(
        settings=PromptCompletionSettings(auto_directive_menu=False),
    )
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        await pilot.press("ctrl+t")
        assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND
        assert _candidate_insertions(ta) == ["@large"]

        await pilot.press("=")
        assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND
        assert _candidate_insertions(ta) == [
            "gpt-5.6-sol",
            "claude-fable-5",
            "anthropic/claude-sonnet-4-5",
        ]
        ta._file_completion_index = 1

        await pilot.press("backspace")
        assert ta.text == "="
        assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND
        assert _candidate_insertions(ta) == ["@large"]
        assert ta._file_completion_index == 0


async def test_second_equals_takes_over_when_alias_rows_are_empty() -> None:
    model_only_entries = tuple(
        entry for entry in explicit_entries() if entry.kind == "model"
    )
    app = ModelExplicitCompletionTestApp(entries=model_only_entries)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        assert ta.text == "="
        assert ta._file_completion_active is False

        await pilot.press("=")
        assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND
        assert _candidate_insertions(ta) == [
            "gpt-5.6-sol",
            "claude-fable-5",
            "anthropic/claude-sonnet-4-5",
        ]


async def test_second_equals_takes_over_when_alias_catalog_is_loading() -> None:
    app = ModelExplicitCompletionTestApp(entries=None)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        with patch.object(type(ta), "_schedule_model_completion_catalog_load"):
            await pilot.press("=")
            assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND
            assert ta._file_completion_candidates[0].display == (
                "Loading model aliases…"
            )

            await pilot.press("=")

        assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND
        assert ta._file_completion_candidates[0].display == "Loading models…"


async def test_double_equals_navigation_preserves_selection_while_filtering() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        await pilot.press("=")
        assert _candidate_insertions(ta) == [
            "gpt-5.6-sol",
            "claude-fable-5",
            "anthropic/claude-sonnet-4-5",
        ]

        await pilot.press("down")
        assert _selected_insertion(ta) == "claude-fable-5"

        await pilot.press("c")
        assert ta.text == "==c"
        assert _candidate_insertions(ta) == ["claude-fable-5"]
        assert _selected_insertion(ta) == "claude-fable-5"

        await pilot.press("backspace")
        assert ta.text == "=="
        assert _candidate_insertions(ta) == [
            "gpt-5.6-sol",
            "claude-fable-5",
            "anthropic/claude-sonnet-4-5",
        ]
        assert _selected_insertion(ta) == "claude-fable-5"


async def test_double_equals_ctrl_l_accepts_selection_without_submit_or_newline() -> (
    None
):
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        await pilot.press("=")
        await pilot.press("f")
        await pilot.press("ctrl+l")

        assert ta.text == "%m:claude-fable-5 "
        assert "\n" not in ta.text
        assert app.submitted == []
        assert ta._file_completion_active is False


async def test_double_equals_third_equals_and_space_dismiss_completion() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        await pilot.press("=")
        await pilot.press("g")
        assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND

        await pilot.press("=")
        assert ta.text == "==g="
        assert ta._file_completion_active is False

        ta.load_text("==g")
        ta.cursor_location = (0, 3)
        assert ta._try_model_explicit_completion() is True
        assert ta._file_completion_active is True

        await pilot.press("space")
        assert ta.text == "==g "
        assert ta._file_completion_active is False


async def test_warm_double_equals_typing_never_builds_catalog_on_key_path() -> None:
    app = ModelExplicitCompletionTestApp()
    with patch(
        "sase.ace.tui.widgets._file_completion_workers.build_model_completion_catalog",
        side_effect=AssertionError("cold catalog builder reached"),
    ):
        async with app.run_test() as pilot:
            ta = app.query_one(PromptInputBar).active_text_area()

            await pilot.press("=")
            await pilot.press("=")
            await pilot.press("g")
            await pilot.press("p")

            assert ta._completion_kind == MODEL_EXPLICIT_COMPLETION_KIND
            assert _candidate_insertions(ta) == ["gpt-5.6-sol"]


async def test_double_equals_accept_replaces_whole_token_from_mid_token_cursor() -> (
    None
):
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()
        ta.load_text("Use ==gpX later")
        ta.cursor_location = (0, len("Use ==gp"))

        await pilot.press("ctrl+t")
        await pilot.press("ctrl+f")

        assert ta.text == "Use %m:gpt-5.6-sol later"
        assert ta.cursor_location == (0, len("Use %m:gpt-5.6-sol "))
        assert app.submitted == []


async def test_double_equals_accept_preserves_context_and_undo_redo() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()
        original = "Keep\t🙂 ==gpX tail\nnext"
        expanded = "Keep\t🙂 %m:gpt-5.6-sol tail\nnext"
        ta.load_text(original)
        ta.cursor_location = (0, len("Keep\t🙂 ==gp"))

        await pilot.press("ctrl+t")
        await pilot.press("ctrl+f")

        assert ta.text == expanded
        assert ta.cursor_location == (0, len("Keep\t🙂 %m:gpt-5.6-sol "))
        assert app.submitted == []
        assert ta._insert_g_prefix_pending is False

        await pilot.press("escape")
        await pilot.press("u")

        assert ta.text == original
        assert ta._file_completion_active is False

        await pilot.press("ctrl+r")

        assert ta.text == expanded
        assert ta._file_completion_active is False
