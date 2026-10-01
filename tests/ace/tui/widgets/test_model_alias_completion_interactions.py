"""Interaction tests for ``=alias`` prompt model completion.

Split from ``test_model_alias_completion``; shared helpers live in
``_model_alias_completion_shared`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

from textual.widgets import Static

from sase.ace.tui.widgets.model_alias_completion import (
    MODEL_ALIAS_COMPLETION_KIND,
    MODEL_ALIAS_MODE_SUBTITLE,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.model_completion import ModelCompletionEntry

from tests._xprompt_model_completion_helpers import (
    clear_model_completion_cache as clear_model_completion_cache,
)

from ._model_alias_completion_shared import ModelAliasCompletionTestApp

__all__ = [
    "clear_model_completion_cache",
    "test_equals_alias_accept_preserves_context_and_undo_redo",
    "test_equals_alias_accept_replaces_whole_token_from_mid_token_cursor",
    "test_equals_alias_auto_opens_and_ctrl_e_expands_without_submit",
    "test_equals_alias_ctrl_l_accepts_selection_without_submit_or_newline",
    "test_equals_alias_ctrl_t_opens_when_auto_directive_menu_is_disabled",
    "test_equals_alias_enter_submits_unexpanded_text_while_menu_is_open",
    "test_equals_alias_navigation_preserves_selection_while_filtering",
    "test_equals_alias_subtitle_omits_missing_description",
]


def _navigation_alias_entries() -> tuple[ModelCompletionEntry, ...]:
    return (
        ModelCompletionEntry(
            value="@large",
            display="@large",
            description="Large model",
            kind="user_alias",
        ),
        ModelCompletionEntry(
            value="@lark",
            display="@lark",
            description="Lark model",
            kind="user_alias",
        ),
        ModelCompletionEntry(
            value="@small",
            display="@small",
            description="Small model",
            kind="implicit_alias",
        ),
        ModelCompletionEntry(
            value="large-model",
            display="large-model",
            description="Concrete model",
            kind="model",
        ),
    )


def _candidate_insertions(text_area: PromptTextArea) -> list[str]:
    return [candidate.insertion for candidate in text_area._file_completion_candidates]


def _selected_insertion(text_area: PromptTextArea) -> str:
    return text_area._file_completion_candidates[
        text_area._file_completion_index
    ].insertion


async def test_equals_alias_auto_opens_and_ctrl_e_expands_without_submit() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = bar.active_text_area()

        await pilot.press("=")
        await pilot.press("l")

        panel = bar.query_one("#prompt-completion", Static)
        assert ta._file_completion_active is True
        assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND
        assert panel.border_title == "model aliases"
        assert [c.insertion for c in ta._file_completion_candidates] == ["@large"]
        assert "Ctrl+F → %m:@large · Large model" in str(panel.border_subtitle)
        assert bar._subtitle_base == MODEL_ALIAS_MODE_SUBTITLE

        await pilot.press("ctrl+f")

        assert ta.text == "%m:@large "
        assert app.submitted == []
        assert ta._file_completion_active is False
        assert ta._insert_g_prefix_pending is False
        assert bar._subtitle_base == bar._mode_subtitle


async def test_equals_alias_enter_submits_unexpanded_text_while_menu_is_open() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        await pilot.press("l")
        assert ta._file_completion_active is True

        await pilot.press("enter")

        assert ta.text == "=l"
        assert app.submitted == ["=l"]
        assert ta._file_completion_active is False


async def test_equals_alias_ctrl_t_opens_when_auto_directive_menu_is_disabled() -> None:
    app = ModelAliasCompletionTestApp(
        settings=PromptCompletionSettings(auto_directive_menu=False, next_word="chain"),
    )
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        await pilot.press("l")
        assert ta._file_completion_active is False

        await pilot.press("ctrl+t")

        assert ta._file_completion_active is True
        assert ta._completion_kind == MODEL_ALIAS_COMPLETION_KIND
        assert [c.insertion for c in ta._file_completion_candidates] == ["@large"]


async def test_equals_alias_navigation_preserves_selection_while_filtering() -> None:
    app = ModelAliasCompletionTestApp(entries=_navigation_alias_entries())
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        assert _candidate_insertions(ta) == ["@large", "@lark", "@small"]

        await pilot.press("down")
        assert _selected_insertion(ta) == "@lark"

        await pilot.press("l")
        assert ta.text == "=l"
        assert _candidate_insertions(ta) == ["@large", "@lark"]
        assert _selected_insertion(ta) == "@lark"

        await pilot.press("backspace")
        assert ta.text == "="
        assert _candidate_insertions(ta) == ["@large", "@lark", "@small"]
        assert _selected_insertion(ta) == "@lark"

        await pilot.press("z")
        assert ta.text == "=z"
        assert ta._file_completion_active is False


async def test_equals_alias_ctrl_l_accepts_selection_without_submit_or_newline() -> (
    None
):
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()

        await pilot.press("=")
        await pilot.press("s")
        await pilot.press("ctrl+l")

        assert ta.text == "%m:@small "
        assert "\n" not in ta.text
        assert app.submitted == []
        assert ta._file_completion_active is False


async def test_equals_alias_subtitle_omits_missing_description() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)

        await pilot.press("=")
        await pilot.press("s")

        panel = bar.query_one("#prompt-completion", Static)
        assert str(panel.border_subtitle) == "Ctrl+F → %m:@small"


async def test_equals_alias_accept_replaces_whole_token_from_mid_token_cursor() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()
        ta.load_text("Use =laX later")
        ta.cursor_location = (0, len("Use =la"))

        await pilot.press("ctrl+t")
        await pilot.press("ctrl+f")

        assert ta.text == "Use %m:@large later"
        assert ta.cursor_location == (0, len("Use %m:@large "))


async def test_equals_alias_accept_preserves_context_and_undo_redo() -> None:
    app = ModelAliasCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptInputBar).active_text_area()
        original = "Keep\t🙂 =laX tail\nnext"
        expanded = "Keep\t🙂 %m:@large tail\nnext"
        ta.load_text(original)
        ta.cursor_location = (0, len("Keep\t🙂 =la"))

        await pilot.press("ctrl+t")
        await pilot.press("ctrl+f")

        assert ta.text == expanded
        assert ta.cursor_location == (0, len("Keep\t🙂 %m:@large "))
        assert app.submitted == []
        assert ta._insert_g_prefix_pending is False

        await pilot.press("escape")
        await pilot.press("u")

        assert ta.text == original
        assert ta._file_completion_active is False

        await pilot.press("ctrl+r")

        assert ta.text == expanded
        assert ta._file_completion_active is False
