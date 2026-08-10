"""Widget-level audit for model-only snippet panes in prompt stacks."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_stack import SnippetPaneTarget
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.ace.tui.widgets._prompt_input_bar_stack_helpers import _PromptBarApp
from tests.ace.tui.widgets.prompt_stack_submit_cancel_test_support import CaptureApp


def _snippet_target(
    trigger: str = "todo",
    *,
    loaded_body: str | None = None,
) -> SnippetPaneTarget:
    return SnippetPaneTarget(
        trigger=trigger,
        read_path="/tmp/sase.yml",
        write_path="/tmp/sase.yml",
        display_path="~/sase.yml",
        apply_target=None,
        via_chezmoi=False,
        exists=False,
        loaded_body=loaded_body,
        loaded_fingerprint=None,
    )


async def _append_snippet_pane(
    pilot: Any,
    bar: PromptInputBar,
    text: str = "snippet body",
) -> None:
    bar._sync_state_from_widgets()
    bar._stack.append_snippet_pane(text, _snippet_target(loaded_body=text))
    bar._rebuild_stack(enter_mode="insert")
    await pilot.pause()
    await pilot.pause()


async def test_snippet_pane_is_mounted_but_not_an_agent_stack() -> None:
    app = _PromptBarApp("agent prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _append_snippet_pane(pilot, bar)

        assert len(app.query(".prompt-input")) == 2
        assert bar.is_multi_pane() is True
        assert bar.is_stacked() is False
        assert bar.border_title == "Prompt"
        assert bar.all_prompt_texts() == ["agent prompt"]
        assert bar.current_prompt_text() == "agent prompt"
        assert bar.xprompt_markdown_for_editor() == "agent prompt"
        assert bar.insert_mode_subtitle() == "[Enter] send  [Esc] normal  [^C] cancel"
        assert not any(entry.key == "s" for entry in bar.g_prefix_hint_entries())


async def test_agent_count_and_separators_skip_snippet_pane() -> None:
    app = _PromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _append_snippet_pane(pilot, bar)

        assert bar.border_title == "Prompt · 2 agents"
        rendered = [
            separator.render().plain
            for separator in app.query(".prompt-stack-separator")
        ]
        assert any("agent 1" in row for row in rendered)
        assert any("agent 2" in row for row in rendered)
        assert any("snippet" in row for row in rendered)
        assert not any("agent 3" in row for row in rendered)


async def test_save_as_and_stash_payloads_ignore_snippet_body() -> None:
    app = CaptureApp("agent prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _append_snippet_pane(pilot, bar)
        bar.focus_item(0)
        await pilot.pause()

        bar.request_save_as_xprompt()
        bar.stash_all_panes()
        await pilot.pause()

        assert len(app.save_as_xprompt_requested) == 1
        save_event = app.save_as_xprompt_requested[0]
        assert [pane.text for pane in save_event.panes] == ["agent prompt"]
        assert save_event.single_pane is True
        assert save_event.snippet_body == "agent prompt"

        assert len(app.stashed) == 1
        stash_event = app.stashed[0]
        assert [pane.text for pane in stash_event.panes] == ["agent prompt"]


async def test_restore_stashed_entries_inserts_above_snippet_and_drops_empty_agent() -> (
    None
):
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _append_snippet_pane(pilot, bar)

        bar.restore_stashed_entries([("restored prompt", "")])
        await pilot.pause()
        await pilot.pause()

        assert bar.all_prompt_texts() == ["restored prompt"]
        assert bar._stack.snippet_index == 1
        assert bar._stack.selected_index == 0
        assert bar.active_text() == "restored prompt"


async def test_whole_stack_submission_ignores_snippet_body() -> None:
    app = CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _append_snippet_pane(pilot, bar, "do not launch")

        bar._handle_whole_stack_submission(bar.active_text_area())
        await pilot.pause()

        assert len(app.submitted) == 1
        event = app.submitted[0]
        assert event.value == "first\n---\nsecond"
        assert event.whole_stack is True


async def test_sync_state_records_cursor_and_vim_mode() -> None:
    app = _PromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        first = list(app.query(PromptTextArea))[0]
        first.cursor_location = (0, 3)
        first._enter_normal_mode()

        bar._sync_state_from_widgets()

        assert bar._stack.items[0].cursor == (0, 3)
        assert bar._stack.items[0].mode == "normal"
