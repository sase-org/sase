"""Tests for post-accept xprompt argument hints in the prompt input."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
)

from ._completion_helpers import CompletionTestApp


def _input(name: str, type_: str, *, position: int = 0) -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=True,
        default_display=None,
        position=position,
    )


def _entry(
    name: str,
    *,
    prefix: str = "#",
    inputs: tuple[XPromptInputHint, ...] = (),
) -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=name,
        insertion=f"{prefix}{name}",
        reference_prefix=prefix,
        kind="xprompt",
        input_signature=None,
        inputs=inputs,
        content_preview=None,
    )


async def test_accepting_required_xprompt_shows_arg_hint_panel() -> None:
    entries = [
        _entry("review", inputs=(_input("path", "path"),)),
        _entry("ship"),
    ]
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)
        with patch(
            "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
            return_value=entries,
        ):
            await pilot.press("ctrl+t")
            await pilot.press("enter")

        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render()
        assert ta.text == "#review"
        assert ta._active_xprompt_arg_hint is not None
        assert "path: path" in rendered.plain
        assert panel.border_title == "xprompt args"


async def test_accepting_xprompt_without_required_inputs_skips_arg_hint() -> None:
    entries = [_entry("plain")]
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#p")
        ta.cursor_location = (0, 2)
        with patch(
            "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
            return_value=entries,
        ):
            assert ta._try_file_completion_tab() is True

        assert ta.text == "#plain"
        assert ta._active_xprompt_arg_hint is None
        assert bar._completion_visible is False


async def test_colon_action_rewrites_reference_and_preserves_surrounding_text() -> None:
    entries = [_entry("review", inputs=(_input("path", "path"),))]
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("before #r after")
        ta.cursor_location = (0, len("before #r"))
        with patch(
            "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
            return_value=entries,
        ):
            await pilot.press("ctrl+t")
            await pilot.press(":")

        assert ta.text == "before #review: after"
        assert ta.cursor_location == (0, len("before #review:"))
        assert ta._active_xprompt_arg_hint is not None


async def test_named_action_uses_snippet_tabstops_for_required_args() -> None:
    entries = [
        _entry(
            "review",
            inputs=(
                _input("path", "path"),
                _input("count", "int", position=1),
            ),
        )
    ]
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#r")
        ta.cursor_location = (0, 2)
        with patch(
            "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
            return_value=entries,
        ):
            await pilot.press("ctrl+t")
            await pilot.press("(")

        assert ta.text == "#review(path=, count=)"
        assert ta.cursor_location == (0, len("#review(path="))
        assert ta._active_xprompt_arg_hint is None
        assert ta._try_advance_tabstop() is True
        assert ta.cursor_location == (0, len("#review(path=, count="))


async def test_submit_cancel_and_escape_clear_arg_hint_state() -> None:
    entries = [_entry("review", inputs=(_input("path", "path"),))]
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#r")
        ta.cursor_location = (0, 2)
        with patch(
            "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
            return_value=entries,
        ):
            await pilot.press("ctrl+t")
        assert ta._active_xprompt_arg_hint is not None

        ta.action_submit_prompt()
        assert ta._active_xprompt_arg_hint is None

        ta.load_text("#r")
        ta.cursor_location = (0, 2)
        with patch(
            "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
            return_value=entries,
        ):
            await pilot.press("ctrl+t")
        assert ta._active_xprompt_arg_hint is not None

        bar = app.query_one(PromptInputBar)
        bar.action_cancel()
        assert ta._active_xprompt_arg_hint is None

        ta.load_text("#r")
        ta.cursor_location = (0, 2)
        with patch(
            "sase.ace.tui.widgets.xprompt_completion.build_xprompt_assist_entries",
            return_value=entries,
        ):
            await pilot.press("ctrl+t")
        assert ta._active_xprompt_arg_hint is not None

        await pilot.press("escape")
        assert ta._active_xprompt_arg_hint is None
        assert ta._vim_mode == "normal"


async def test_typed_colon_reference_shows_arg_hint_panel() -> None:
    entries = [_entry("review", inputs=(_input("path", "path"),))]
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#review:")
        ta.cursor_location = (0, len("#review:"))
        with patch(
            "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
            return_value=entries,
        ):
            ta._refresh_xprompt_arg_hint_from_cursor()

        panel = bar.query_one("#prompt-completion", Static)
        assert ta._active_xprompt_arg_hint is not None
        assert "path: path" in panel.render().plain
        assert panel.border_title == "xprompt args"


async def test_typed_hint_detection_skips_active_snippet_tabstops() -> None:
    entries = [_entry("review", inputs=(_input("path", "path"),))]
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#review:")
        ta.cursor_location = (0, len("#review:"))
        ta._snippet_tabstops = [len("#review:")]
        with patch(
            "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
            return_value=entries,
        ):
            ta._refresh_xprompt_arg_hint_from_cursor()

        panel = bar.query_one("#prompt-completion", Static)
        assert ta._active_xprompt_arg_hint is None
        assert panel.has_class("hidden")


async def test_snippet_modal_insertion_opens_same_arg_hint_path() -> None:
    entries = [_entry("review", inputs=(_input("path", "path"),))]
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)
        with patch(
            "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
            return_value=entries,
        ):
            bar.insert_snippet("review")

        assert ta.text == "#review"
        assert ta._active_xprompt_arg_hint is not None
        assert ta._active_xprompt_arg_hint.trigger_mode == "accepted"


async def test_typed_hint_uses_project_from_leading_vcs_tag() -> None:
    entries = [_entry("local", inputs=(_input("path", "path"),))]
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        prompt = "#gh:sase #local:"
        ta.load_text(prompt)
        ta.cursor_location = (0, len(prompt))

        def build_entries(project: str | None = None) -> list[XPromptAssistEntry]:
            return entries if project == "sase" else []

        with (
            patch(
                "sase.ace.tui.widgets.prompt_text_area.extract_vcs_workflow_tag",
                return_value="#gh:sase ",
            ),
            patch(
                "sase.ace.tui.widgets.prompt_text_area.extract_project_from_vcs_tag",
                return_value="sase",
            ),
            patch(
                "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
                side_effect=build_entries,
            ) as build,
        ):
            ta._refresh_xprompt_arg_hint_from_cursor()

        assert ta._active_xprompt_arg_hint is not None
        build.assert_called_once_with(project="sase")
