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
from sase.core.snippet_session_facade import (
    SnippetSessionState,
    _SnippetSpan,
    _SnippetStop,
)

from ._completion_helpers import CompletionTestApp


def _input(
    name: str,
    type_: str,
    *,
    position: int = 0,
    description: str | None = None,
) -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=True,
        default_display=None,
        position=position,
        description=description,
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


def _seed_entries(
    ta: PromptTextArea,
    entries: list[XPromptAssistEntry],
    project: str | None = None,
) -> None:
    ta._xprompt_arg_assist_entries_by_project[project] = entries


async def test_accepting_required_xprompt_shows_arg_hint_panel() -> None:
    entries = [
        _entry(
            "review",
            inputs=(_input("path", "path", description="File to inspect."),),
        ),
        _entry("ship"),
    ]
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)
        _seed_entries(ta, entries)
        await pilot.press("ctrl+t")
        await pilot.press("enter")

        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render()
        assert ta.text == "#review:"
        assert ta._active_xprompt_arg_hint is not None
        assert "path: path" in rendered.plain
        assert "File to inspect." in rendered.plain
        assert panel.border_title == "xprompt args"


async def test_accepting_xprompt_without_required_inputs_skips_arg_hint() -> None:
    entries = [_entry("plain")]
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#p")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, entries)
        assert ta._try_file_completion_tab() is True

        assert ta.text == "#plain "
        assert ta._active_xprompt_arg_hint is None
        assert bar._completion_visible is False


async def test_colon_action_rewrites_reference_and_preserves_surrounding_text() -> None:
    entries = [_entry("review", inputs=(_input("path", "path"),))]
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("before # after")
        ta.cursor_location = (0, len("before #"))
        _seed_entries(ta, entries)
        bar.insert_snippet("review")
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
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)
        _seed_entries(ta, entries)
        bar.insert_snippet("review")
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
        _seed_entries(ta, entries)
        await pilot.press("ctrl+t")
        assert ta._active_xprompt_arg_hint is not None

        ta.action_submit_prompt()
        assert ta._active_xprompt_arg_hint is None

        ta.load_text("#r")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, entries)
        await pilot.press("ctrl+t")
        assert ta._active_xprompt_arg_hint is not None

        bar = app.query_one(PromptInputBar)
        bar.action_cancel()
        assert ta._active_xprompt_arg_hint is None

        ta.load_text("#r")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, entries)
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
        _seed_entries(ta, entries)
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
        stop = len("#review:")
        ta._snippet_session = SnippetSessionState(
            stops=(_SnippetStop(offset=stop, session=0),),
            index=0,
            sessions=(_SnippetSpan(id=0, start=0, end=stop),),
            next_session_id=1,
        )
        _seed_entries(ta, entries)
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
        _seed_entries(ta, entries)
        bar.insert_snippet("review")

        assert ta.text == "#review"
        assert ta._active_xprompt_arg_hint is not None
        assert ta._active_xprompt_arg_hint.trigger_mode == "accepted"


async def test_snippet_modal_smart_insertion_adds_trailing_space_without_args() -> None:
    entry = _entry("plain")
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)

        bar.insert_snippet("plain", entry)

        assert ta.text == "#plain "
        assert ta._active_xprompt_arg_hint is None


async def test_snippet_modal_smart_insertion_skips_space_before_punctuation() -> None:
    entry = _entry("plain")
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#)")
        ta.cursor_location = (0, 1)

        bar.insert_snippet("plain", entry)

        assert ta.text == "#plain)"
        assert ta.cursor_location == (0, len("#plain"))
        assert ta._active_xprompt_arg_hint is None


async def test_snippet_modal_smart_insertion_adds_path_colon_hint() -> None:
    entry = _entry("review", inputs=(_input("path", "path"),))
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)

        bar.insert_snippet("review", entry)

        assert ta.text == "#review:"
        assert ta._active_xprompt_arg_hint is not None
        assert ta._active_xprompt_arg_hint.trigger_mode == "colon"


async def test_snippet_modal_smart_insertion_text_at_line_end_adds_double_colon_space() -> (
    None
):
    entry = _entry("ask", inputs=(_input("body", "text"),))
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)

        bar.insert_snippet("ask", entry)

        # End-of-line required-text insertion lands the free-form ``:: ``
        # shorthand with the cursor parked just after the delimiter space.
        assert ta.text == "#ask:: "
        assert ta.cursor_location == (0, len("#ask:: "))
        # The committed trailing space ends structured arg hinting.
        assert ta._active_xprompt_arg_hint is None


async def test_snippet_modal_smart_insertion_text_before_text_keeps_single_space() -> (
    None
):
    entry = _entry("ask", inputs=(_input("body", "text"),))
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("# after")
        ta.cursor_location = (0, 1)

        bar.insert_snippet("ask", entry)

        # Inserting before existing text keeps the bare ``::`` so the existing
        # following space is the single delimiter -- not a doubled space.
        assert ta.text == "#ask:: after"
        assert ta.cursor_location == (0, len("#ask::"))
        assert ta._active_xprompt_arg_hint is None


async def test_snippet_modal_smart_insertion_adds_multi_input_skeleton() -> None:
    entry = _entry(
        "many",
        inputs=(
            _input("path", "path"),
            _input("body", "text", position=1),
        ),
    )
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)

        bar.insert_snippet("many", entry)

        assert ta.text == "#many()"
        assert ta.cursor_location == (0, len("#many("))
        assert ta._active_xprompt_arg_hint is not None
        assert ta._active_xprompt_arg_hint.trigger_mode == "paren"


async def test_snippet_modal_smart_insertion_preserves_standalone_marker() -> None:
    entry = _entry(
        "run",
        prefix="#!",
        inputs=(_input("target", "line"),),
    )
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)

        bar.insert_snippet("!run", entry)

        assert ta.text == "#!run:"
        assert ta._active_xprompt_arg_hint is not None


async def test_snippet_modal_smart_insertion_uses_selected_metadata() -> None:
    entry = _entry("local", inputs=(_input("path", "path"),))
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#gh:sase #")
        ta.cursor_location = (0, len("#gh:sase #"))
        bar.insert_snippet("local", entry)

        assert ta.text == "#gh:sase #local:"
        assert ta._active_xprompt_arg_hint is not None


async def test_typed_hint_uses_project_from_leading_vcs_tag() -> None:
    entries = [_entry("local", inputs=(_input("path", "path"),))]
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        prompt = "#gh:sase #local:"
        ta.load_text(prompt)
        ta.cursor_location = (0, len(prompt))
        _seed_entries(ta, entries, project="sase")

        with (
            patch(
                "sase.ace.tui.widgets.prompt_text_area.extract_vcs_workflow_tag",
                return_value="#gh:sase ",
            ),
            patch(
                "sase.ace.tui.widgets.prompt_text_area.extract_project_from_vcs_tag",
                return_value="sase",
            ),
        ):
            ta._refresh_xprompt_arg_hint_from_cursor()

        assert ta._active_xprompt_arg_hint is not None
