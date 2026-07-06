"""Vim editor adoption tests for ``UserQuestionModal`` freeform inputs."""

from __future__ import annotations

from textual.app import App
from textual.widgets import SelectionList

from sase.ace.tui.modals.user_question_modal import UserQuestionModal
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False


def _questions() -> list[dict[str, object]]:
    return [
        {
            "question": "What should happen?",
            "options": [{"label": "Proceed", "description": "Use the default"}],
        }
    ]


async def test_global_note_escape_is_two_stage() -> None:
    async with _TestApp().run_test(size=(100, 30)) as pilot:
        modal = UserQuestionModal(_questions())
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_global_note()
        await pilot.pause()

        editor = modal.query_one("#user-question-global-input", SingleLineVimTextArea)
        assert pilot.app.focused is editor
        assert modal._input_mode == "global"

        await pilot.press("escape")
        await pilot.pause()

        assert editor._vim_mode == "normal"
        assert modal._input_mode == "global"
        assert not editor.has_class("hidden")

        await pilot.press("escape")
        await pilot.pause()

        assert modal._input_mode is None
        assert editor.has_class("hidden")
        assert isinstance(pilot.app.focused, SelectionList)
