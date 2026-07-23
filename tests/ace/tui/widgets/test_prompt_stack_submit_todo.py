"""Widget tests for TODO confirmation during prompt-stack submission."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button

from sase.ace.tui.modals import ConfirmActionModal
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_stack import XPromptBinding
from tests.ace.tui.widgets.prompt_stack_submit_cancel_test_support import (
    CaptureApp,
    submit_current_pane,
)


@pytest.mark.parametrize("cancel_key", ["n", "escape", "q", None])
async def test_single_prompt_todo_confirmation_rejects_without_mutation(
    cancel_key: str | None,
) -> None:
    prompt = "TODO(owner): finish this exact draft"
    app = CaptureApp(prompt)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ConfirmActionModal)
        modal = app.screen
        assert modal._message == (
            "This submission contains 1 visible TODO marker. Launch it anyway?"
        )
        assert modal.query_one("#cancel-btn", Button).has_focus
        assert ("y", "confirm", "Yes") in modal.BINDINGS
        assert ("n", "cancel", "No") in modal.BINDINGS
        assert app.submitted == []
        assert bar.all_prompt_texts() == [prompt]

        if cancel_key is None:
            modal.dismiss(None)
        else:
            await pilot.press(cancel_key)
        await pilot.pause()

        assert app.submitted == []
        assert app.cancelled == []
        assert app.stashed == []
        assert bar.all_prompt_texts() == [prompt]
        assert bar.active_text_area().has_focus


async def test_single_prompt_todo_confirmation_launches_unchanged_once() -> None:
    prompt = "TODO: keep this literal #git:sase prompt"
    app = CaptureApp(prompt)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmActionModal)

        await pilot.press("y")
        await pilot.pause()

        assert len(app.submitted) == 1
        event = app.submitted[0]
        assert event.value == prompt
        assert event.keep_bar is False
        assert event.whole_stack is False


@pytest.mark.parametrize(
    "prompt",
    [
        "plain prompt with no draft marker",
        "`TODO: inline literal`",
        "```\nTODO(owner): fenced literal\n```",
        "lowercase todo remains ordinary",
        "TODOS TODO2 preTODO remain ordinary",
    ],
)
async def test_todo_free_and_literal_shaped_prompts_submit_immediately(
    prompt: str,
) -> None:
    app = CaptureApp(prompt)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert not isinstance(app.screen, ConfirmActionModal)
        assert [event.value for event in app.submitted] == [prompt]


@pytest.mark.parametrize("mode", ["feedback", "approve_prompt"])
async def test_non_launch_prompt_modes_skip_todo_confirmation(mode: str) -> None:
    prompt = "TODO: mode-specific response"
    app = CaptureApp(prompt, mode=mode)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert not isinstance(app.screen, ConfirmActionModal)
        assert [event.value for event in app.submitted] == [prompt]


async def test_current_pane_submit_ignores_todo_in_unsent_pane() -> None:
    app = CaptureApp("TODO: unsent first pane\n---\nready second pane")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await submit_current_pane(pilot, bar, "direct")

        assert not isinstance(app.screen, ConfirmActionModal)
        assert [event.value for event in app.submitted] == ["ready second pane"]
        assert bar.all_prompt_texts() == ["TODO: unsent first pane"]


@pytest.mark.parametrize("route", ["direct", "chooser"])
async def test_selected_pane_todo_confirmation_preserves_then_commits(
    route: str,
    tmp_path: Path,
) -> None:
    prompt = (
        "---\ndescription: keep\n---\nfirst TODO: draft\n---\nsecond TODO(owner): ship"
    )
    app = CaptureApp(prompt)

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        source = tmp_path / "bound.md"
        source.write_text(prompt, encoding="utf-8")
        binding = XPromptBinding.for_file(source)
        bar._stack.bind(binding, source_markdown=prompt)
        original_texts = bar.all_prompt_texts()
        original_selection = bar._stack.selected_index
        original_frontmatter = bar.current_frontmatter()

        await submit_current_pane(pilot, bar, route)

        assert isinstance(app.screen, ConfirmActionModal)
        assert app.submitted == []
        assert bar.all_prompt_texts() == original_texts
        assert bar._stack.selected_index == original_selection
        assert bar.current_frontmatter() == original_frontmatter
        assert bar._stack.binding is binding

        await pilot.press("n")
        await pilot.pause()

        assert app.submitted == []
        assert bar.all_prompt_texts() == original_texts
        assert bar._stack.selected_index == original_selection
        assert bar.current_frontmatter() == original_frontmatter
        assert bar._stack.binding is binding

        await submit_current_pane(pilot, bar, route)
        assert isinstance(app.screen, ConfirmActionModal)
        await pilot.press("y")
        await pilot.pause()
        await pilot.pause()

        assert len(app.submitted) == 1
        event = app.submitted[0]
        assert event.value == ("---\ndescription: keep\n---\nsecond TODO(owner): ship")
        assert event.keep_bar is True
        assert event.whole_stack is False
        assert bar.all_prompt_texts() == ["first TODO: draft"]
        assert bar.current_frontmatter() == original_frontmatter
        assert bar._stack.binding is binding


async def test_whole_stack_todo_confirmation_counts_submitted_markers() -> None:
    prompt = (
        "TODO: first `TODO: inline literal`\n"
        "---\n"
        "```\nTODO(owner): fenced literal\n```\n"
        "---\n"
        "TODO(owner): third"
    )
    app = CaptureApp(prompt)

    async with app.run_test(size=(80, 32)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        original_texts = bar.all_prompt_texts()
        original_selection = bar._stack.selected_index

        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

        assert isinstance(app.screen, ConfirmActionModal)
        assert app.screen._message == (
            "This submission contains 2 visible TODO markers. Launch it anyway?"
        )
        assert app.submitted == []

        await pilot.press("escape")
        await pilot.pause()
        assert bar.all_prompt_texts() == original_texts
        assert bar._stack.selected_index == original_selection

        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmActionModal)
        await pilot.press("y")
        await pilot.pause()

        assert len(app.submitted) == 1
        event = app.submitted[0]
        assert event.value == prompt
        assert event.keep_bar is False
        assert event.whole_stack is True


async def test_todo_confirmation_fails_closed_after_stack_rebuild() -> None:
    app = CaptureApp("TODO: original")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmActionModal)

        bar.load_stack_from_xprompt_markdown("replacement\n---\nother")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert app.submitted == []
        assert bar.all_prompt_texts() == ["replacement", "other"]


async def test_todo_confirmation_fails_closed_after_origin_unmount() -> None:
    app = CaptureApp("TODO: original")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmActionModal)

        await bar.remove()
        await pilot.pause()
        assert not app.query(PromptInputBar)
        await pilot.press("y")
        await pilot.pause()

        assert app.submitted == []
        assert not app.query(PromptInputBar)
