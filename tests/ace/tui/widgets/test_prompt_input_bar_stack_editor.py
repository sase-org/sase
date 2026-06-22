"""Prompt input bar stack tests for editor keybinding behavior."""

from __future__ import annotations

from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._prompt_input_bar_stack_helpers import (
    _RecordingPromptBarApp,
)


# --- all-pane editor (prompt editor prefix when stacked) -------------------


async def test_action_open_editor_on_single_pane_requests_active_text() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.active_text_area().action_open_editor()
        await pilot.pause()

        # A single-pane bar posts the single-pane editor request, never the
        # all-editor message.
        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "solo prompt"
        assert app.all_editor_requests == []


async def test_action_open_editor_on_stacked_bar_requests_whole_stack() -> None:
    app = _RecordingPromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.focus_item(1)  # the active pane must not narrow the editor scope
        await pilot.pause()

        bar.active_text_area().action_open_editor()
        await pilot.pause()

        # A multi-pane stack posts exactly one all-editor message and never the
        # single-pane editor request; the serialized buffer is the whole stack
        # joined with blank-line-padded ``---`` separators.
        assert len(app.all_editor_requests) == 1
        assert app.editor_requests == []
        assert (
            bar.xprompt_markdown_for_editor()
            == "first\n\n---\n\nsecond\n\n---\n\nthird"
        )


async def test_action_open_editor_in_feedback_mode_requests_single_pane() -> None:
    app = _RecordingPromptBarApp("draft feedback", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(PromptInputBar)
        bar.active_text_area().action_open_editor()
        await pilot.pause()

        # Feedback bars never stack, so editor access stays single-pane and never
        # reaches the all-editor (multi-agent) surface.
        assert len(app.editor_requests) == 1
        assert app.all_editor_requests == []


async def test_focused_pane_ctrl_g_starts_prefix_and_shadows_global_binding() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert app.focused is bar.active_text_area()

        await pilot.press("ctrl+g")
        await pilot.pause()

        # The focused prompt owns the prefix, so the app-level "edit last VCS
        # xprompt" action never runs and no editor opens until a continuation.
        assert app.editor_requests == []
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0
        assert bar.active_text_area()._insert_g_prefix_pending is True


async def test_focused_normal_mode_ctrl_g_starts_prefix_and_shadows_global_binding() -> (
    None
):
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("escape", "ctrl+g")
        await pilot.pause()

        # NORMAL-mode ``Ctrl+G`` opens the same prompt-local ``^G`` prefix that
        # INSERT-mode ``Ctrl+G`` does instead of being swallowed: the app-level
        # "edit last VCS xprompt" binding stays shadowed and no editor opens
        # until a continuation key.
        text_area = bar.active_text_area()
        assert text_area._vim_mode == "normal"
        assert text_area._normal_g_prefix_pending is True
        assert app.editor_requests == []
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0

        panel = bar.query_one("#prompt-g-prefix-hints", Static)
        assert not panel.has_class("hidden")
        assert panel.border_title == " ^G "


async def test_normal_ctrl_g_g_on_single_pane_requests_active_text() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape", "ctrl+g", "g")
        await pilot.pause()

        # NORMAL-mode ``Ctrl+G g`` opens the editor just like INSERT-mode
        # ``Ctrl+G g`` and never triggers the app-level binding.
        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "solo prompt"
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0


async def test_normal_ctrl_g_ctrl_g_on_single_pane_requests_active_text() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape", "ctrl+g", "ctrl+g")
        await pilot.pause()

        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "solo prompt"
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0


async def test_normal_ctrl_g_g_on_stacked_bar_requests_whole_stack() -> None:
    app = _RecordingPromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape", "ctrl+g", "g")
        await pilot.pause()

        assert len(app.all_editor_requests) == 1
        assert app.editor_requests == []
        assert app.global_editor_calls == 0


async def test_ctrl_g_g_on_single_pane_requests_active_text() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+g", "g")
        await pilot.pause()

        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "solo prompt"
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0


async def test_ctrl_g_ctrl_g_on_single_pane_requests_active_text() -> None:
    app = _RecordingPromptBarApp("solo prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+g", "ctrl+g")
        await pilot.pause()

        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "solo prompt"
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0


async def test_ctrl_g_g_on_stacked_bar_requests_whole_stack() -> None:
    app = _RecordingPromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+g", "g")
        await pilot.pause()

        assert len(app.all_editor_requests) == 1
        assert app.editor_requests == []
        assert app.global_editor_calls == 0


async def test_ctrl_g_g_in_feedback_mode_requests_single_pane() -> None:
    app = _RecordingPromptBarApp("draft feedback", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("ctrl+g", "g")
        await pilot.pause()

        assert len(app.editor_requests) == 1
        assert app.editor_requests[0].current_text == "draft feedback"
        assert app.all_editor_requests == []
        assert app.global_editor_calls == 0


def test_prompt_text_area_no_longer_binds_direct_ctrl_g_editor() -> None:
    actions = {entry[0]: entry[1] for entry in PromptTextArea.BINDINGS}
    assert "ctrl+g" not in actions
    # ``ctrl+shift+g`` is gone too: editor access lives behind the prompt-local
    # insert-mode ``Ctrl+G`` prefix and the programmatic action stays intact.
    assert "ctrl+shift+g" not in actions
