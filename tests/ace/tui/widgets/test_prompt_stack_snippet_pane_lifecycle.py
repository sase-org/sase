"""Widget tests for snippet target pane lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.modals import ConfirmActionModal
from sase.ace.tui.modals.snippet_name_modal import SnippetNameResult
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.snippet_targets import SnippetSaveTarget
from tests.ace.tui.widgets.prompt_stack_submit_cancel_test_support import CaptureApp


def _save_target(tmp_path: Path, name: str = "sase.yml") -> SnippetSaveTarget:
    path = tmp_path / name
    return SnippetSaveTarget(
        read_path=path,
        write_path=path,
        apply_target=None,
        via_chezmoi=False,
        display_path=f"~/.config/sase/{name}",
        source="configured",
        fallback_reason=None,
    )


def _name_result(
    tmp_path: Path,
    *,
    trigger: str = "todo",
    existing_body: str | None = None,
    derived_from: str | None = None,
) -> SnippetNameResult:
    return SnippetNameResult(
        trigger=trigger,
        target=_save_target(tmp_path),
        exists=existing_body is not None or derived_from is not None,
        existing_body=existing_body,
        derived_from=derived_from,
    )


async def _open_snippet(
    pilot: Any,
    bar: PromptInputBar,
    result: SnippetNameResult,
    *,
    origin_pane_id: str | None = None,
    destination_exists: bool = False,
) -> None:
    if origin_pane_id is None:
        origin_pane_id = bar.active_text_area().id or ""
    assert bar.open_snippet_target_pane(
        result,
        origin_pane_id=origin_pane_id,
        destination_exists=destination_exists,
        loaded_fingerprint=None,
    )
    await pilot.pause()
    await pilot.pause()


async def test_gt_and_ctrl_g_t_request_snippet_target(tmp_path: Path) -> None:
    del tmp_path
    app = CaptureApp("draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await pilot.press("escape", "g", "t")
        await pilot.pause()

        assert len(app.snippet_target_requested) == 1
        event = app.snippet_target_requested[0]
        assert event.origin_bar is bar
        assert event.origin_pane_id == bar.active_text_area().id
        assert event.initial_trigger == ""

        await pilot.press("i", "ctrl+g", "t")
        await pilot.pause()

        assert len(app.snippet_target_requested) == 2
        assert app.snippet_target_requested[1].initial_trigger == ""


async def test_open_snippet_pane_prefills_body_and_lands_last(
    tmp_path: Path,
) -> None:
    app = CaptureApp("agent prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await _open_snippet(
            pilot,
            bar,
            _name_result(tmp_path, existing_body="snippet body"),
            destination_exists=True,
        )

        assert bar._stack.snippet_index == 1
        assert bar._stack.selected_item.is_snippet_pane
        assert bar.all_prompt_texts() == ["agent prompt"]
        assert bar.active_text() == "snippet body"
        assert bar.active_text_area()._vim_mode == "insert"
        assert bar.active_text_area().cursor_location == (0, len("snippet body"))


async def test_close_snippet_restores_exact_cursor_and_mode_with_clamp(
    tmp_path: Path,
) -> None:
    app = CaptureApp("alpha\nbeta")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        origin = bar.active_text_area()
        origin.cursor_location = (1, 2)
        origin._enter_normal_mode()
        origin_id = origin.id or ""

        await _open_snippet(
            pilot,
            bar,
            _name_result(tmp_path, existing_body="snippet body"),
            origin_pane_id=origin_id,
            destination_exists=True,
        )

        agent_area = app.query_one(
            f"#{bar._pane_id(bar._stack.items[0])}", PromptTextArea
        )
        agent_area.text = "a"
        bar._sync_state_from_widgets()

        assert bar.close_snippet_target("discarded")
        await pilot.pause()
        await pilot.pause()

        restored = bar.active_text_area()
        assert restored is app.query_one(f"#{bar._pane_id(bar._stack.items[0])}")
        assert restored.text == "a"
        assert restored.cursor_location == (0, 1)
        assert restored._vim_mode == "normal"
        assert restored.has_focus


async def test_gt_retargets_existing_snippet_without_replacing_body(
    tmp_path: Path,
) -> None:
    app = CaptureApp("agent prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await _open_snippet(
            pilot,
            bar,
            _name_result(tmp_path, trigger="old", existing_body="loaded"),
            destination_exists=True,
        )
        snippet_area = bar.active_text_area()
        snippet_area.text = "user draft"
        bar._sync_state_from_widgets()

        assert bar.open_snippet_target_pane(
            _name_result(tmp_path, trigger="new", existing_body="new loaded"),
            origin_pane_id=snippet_area.id or "",
            destination_exists=True,
            loaded_fingerprint=None,
        )

        assert bar.active_text() == "user draft"
        target = bar._stack.snippet_item.snippet_target
        assert target is not None
        assert target.trigger == "new"
        assert target.loaded_body == "new loaded"
        assert bar._stack.snippet_index == 1


async def test_enter_in_snippet_pane_requests_save_without_launch(
    tmp_path: Path,
) -> None:
    app = CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet(pilot, bar, _name_result(tmp_path, existing_body="body"))

        await pilot.press("enter")
        await pilot.pause()

        assert app.submitted == []
        assert len(app.snippet_pane_save_requested) == 1
        assert app.snippet_pane_save_requested[0].origin_bar is bar


async def test_ctrl_c_on_dirty_snippet_confirms_then_discards(
    tmp_path: Path,
) -> None:
    app = CaptureApp("agent prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet(
            pilot,
            bar,
            _name_result(tmp_path, existing_body="loaded"),
            destination_exists=True,
        )
        bar.active_text_area().text = "edited"

        await pilot.press("ctrl+c")
        await pilot.pause()

        assert isinstance(app.screen, ConfirmActionModal)
        assert app.cancelled == []
        await pilot.press("n")
        await pilot.pause()
        assert bar._stack.has_snippet_pane
        assert bar.active_text_area().has_focus

        await pilot.press("ctrl+c")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        await pilot.pause()

        assert not bar._stack.has_snippet_pane
        assert app.cancelled == []
        assert bar.active_text() == "agent prompt"


async def test_dirty_snippet_guard_confirms_single_agent_launch(
    tmp_path: Path,
) -> None:
    app = CaptureApp("agent prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet(
            pilot,
            bar,
            _name_result(tmp_path, existing_body="loaded"),
            destination_exists=True,
        )
        bar.active_text_area().text = "edited"
        bar._sync_state_from_widgets()
        bar.focus_item(0)
        await pilot.pause()

        bar._handle_text_submission("", bar.active_text_area())
        await pilot.pause()

        assert isinstance(app.screen, ConfirmActionModal)
        assert app.submitted == []

        await pilot.press("y")
        await pilot.pause()
        await pilot.pause()

        assert len(app.submitted) == 1
        assert app.submitted[0].value == "agent prompt"


async def test_dirty_snippet_guard_confirms_final_agent_cancel(
    tmp_path: Path,
) -> None:
    app = CaptureApp("agent prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet(
            pilot,
            bar,
            _name_result(tmp_path, existing_body="loaded"),
            destination_exists=True,
        )
        bar.active_text_area().text = "edited"
        bar._sync_state_from_widgets()
        bar.focus_item(0)
        await pilot.pause()

        bar.action_cancel()
        await pilot.pause()

        assert isinstance(app.screen, ConfirmActionModal)
        assert app.cancelled == []

        await pilot.press("y")
        await pilot.pause()
        await pilot.pause()

        assert len(app.cancelled) == 1
        assert app.cancelled[0].cancelled_text == "agent prompt"


@pytest.mark.parametrize(
    ("action_name", "assertion"),
    [
        (
            "whole_stack_submit",
            lambda app, bar: (
                len(app.submitted) == 1
                and app.submitted[0].value == "first\n---\nsecond"
            ),
        ),
        (
            "cancel_all",
            lambda app, bar: (
                len(app.cancelled) == 1
                and app.cancelled[0].cancelled_text == "first\n---\nsecond"
            ),
        ),
        (
            "stash_all",
            lambda app, bar: (
                len(app.stashed) == 1
                and [pane.text for pane in app.stashed[0].panes] == ["first", "second"]
            ),
        ),
        (
            "stash_all_and_load",
            lambda app, bar: (
                len(app.stashed) == 1 and bar.all_prompt_texts() == ["replacement"]
            ),
        ),
        (
            "load_stack",
            lambda app, bar: bar.all_prompt_texts() == ["replacement"],
        ),
    ],
)
async def test_dirty_snippet_guard_confirms_stack_replacement_paths(
    tmp_path: Path,
    action_name: str,
    assertion: Callable[[CaptureApp, PromptInputBar], bool],
) -> None:
    app = CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet(
            pilot,
            bar,
            _name_result(tmp_path, existing_body="loaded"),
            destination_exists=True,
        )
        bar.active_text_area().text = "edited"

        if action_name == "whole_stack_submit":
            bar._handle_whole_stack_submission(bar.active_text_area())
        elif action_name == "cancel_all":
            bar.action_cancel_all()
        elif action_name == "stash_all":
            bar.stash_all_panes()
        elif action_name == "stash_all_and_load":
            bar.stash_all_and_load_xprompt_markdown("replacement")
        else:
            bar.load_stack_from_xprompt_markdown("replacement")
        await pilot.pause()

        assert isinstance(app.screen, ConfirmActionModal)
        assert not assertion(app, bar)

        await pilot.press("y")
        await pilot.pause()
        await pilot.pause()

        assert assertion(app, bar)


async def test_clean_snippet_drops_without_discard_confirmation(
    tmp_path: Path,
) -> None:
    app = CaptureApp("agent prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet(
            pilot,
            bar,
            _name_result(tmp_path, existing_body="loaded"),
            destination_exists=True,
        )

        bar.action_cancel_all()
        await pilot.pause()

        assert not isinstance(app.screen, ConfirmActionModal)
        assert len(app.cancelled) == 1
        assert app.cancelled[0].cancelled_text == "agent prompt"
