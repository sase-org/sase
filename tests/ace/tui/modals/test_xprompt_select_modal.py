"""Tests for the ACE xprompt selection modal."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from textual.app import App
from textual.widgets import OptionList

from sase.ace.tui.modals.xprompt_select_modal import XPromptSelectModal
from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_models import Workflow, WorkflowStep


class _SuspendRecorder:
    def __init__(self) -> None:
        self.entered_count = 0
        self.active = False

    def __enter__(self) -> None:
        self.entered_count += 1
        self.active = True

    def __exit__(self, *_args: object) -> None:
        self.active = False


class _TestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.suspend_recorder = _SuspendRecorder()
        self.notifications: list[tuple[str, str]] = []

    def suspend(self) -> _SuspendRecorder:
        return self.suspend_recorder

    def notify(
        self,
        message: str,
        *,
        severity: str = "information",
        **_: object,
    ) -> None:
        self.notifications.append((message, severity))


def _simple_workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="prompt", prompt_part="body")])


def _multi_agent_xprompt_workflow(name: str) -> Workflow:
    return Workflow(
        name=name,
        steps=[WorkflowStep(name="prompt", prompt_part="one\n---\ntwo")],
    )


def _standalone_workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="run", agent="do it")])


def _source_workflow(name: str, source_path: str | None) -> Workflow:
    return Workflow(
        name=name,
        source_path=source_path,
        steps=[WorkflowStep(name="prompt", prompt_part="body")],
    )


def test_xprompt_select_returns_suffix_for_existing_hash_trigger() -> None:
    prompts = {
        "commit": _simple_workflow("commit"),
        "multi": _multi_agent_xprompt_workflow("multi"),
        "sync": _standalone_workflow("sync"),
    }
    with patch(
        "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
        return_value=prompts,
    ):
        modal = XPromptSelectModal()

    assert modal._insertion_suffix("commit") == "commit"
    assert modal._insertion_suffix("multi") == "!multi"
    assert modal._insertion_suffix("sync") == "!sync"


def test_xprompt_select_payload_includes_assist_entry_for_smart_args() -> None:
    prompts = {
        "review": Workflow(
            name="review",
            inputs=[InputArg(name="path", type=InputType.PATH)],
            steps=[WorkflowStep(name="prompt", prompt_part="body")],
        ),
        "sync": Workflow(
            name="sync",
            inputs=[InputArg(name="target", type=InputType.LINE)],
            steps=[WorkflowStep(name="run", agent="do it")],
        ),
    }
    with patch(
        "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
        return_value=prompts,
    ):
        modal = XPromptSelectModal()

    review = modal._selection_for_name("review")
    assert review.suffix == "review"
    assert review.entry is not None
    assert review.entry.insertion == "#review"
    assert [inp.name for inp in review.entry.inputs] == ["path"]

    sync = modal._selection_for_name("sync")
    assert sync.suffix == "!sync"
    assert sync.entry is not None
    assert sync.entry.insertion == "#!sync"


def test_xprompt_select_filters_and_previews_descriptions() -> None:
    prompts = {
        "review": Workflow(
            name="review",
            description="Review a selected diff.",
            inputs=[
                InputArg(
                    name="diff",
                    type=InputType.PATH,
                    description="Diff file to inspect.",
                )
            ],
            steps=[WorkflowStep(name="prompt", prompt_part="body")],
        ),
        "ship": _standalone_workflow("ship"),
    }
    with patch(
        "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
        return_value=prompts,
    ):
        modal = XPromptSelectModal()

    assert modal._get_filtered_names("selected diff") == ["review"]
    assert modal._get_filtered_names("file to inspect") == ["review"]
    preview = modal._all_items["review"][0]
    assert "Review a selected diff." in preview
    assert "Diff file to inspect." in preview


async def test_xprompt_select_action_opens_selected_source_path(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "review.md"
    prompts = {
        "build": _source_workflow("build", str(tmp_path / "build.md")),
        "review": _source_workflow("review", str(source_path)),
    }
    run_calls: list[tuple[list[str], bool, bool]] = []

    def fake_run(args: list[str], *, check: bool) -> None:
        app = modal.app
        run_calls.append((args, check, app.suspend_recorder.active))

    with (
        patch(
            "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
            return_value=prompts,
        ),
        patch.dict("os.environ", {"EDITOR": "test-editor"}, clear=False),
        patch(
            "sase.ace.tui.modals.xprompt_select_modal.subprocess.run",
            side_effect=fake_run,
        ),
    ):
        modal = XPromptSelectModal()
        async with _TestApp().run_test() as pilot:
            pilot.app.push_screen(modal)
            await pilot.pause()
            option_list = modal.query_one("#xprompt-list", OptionList)
            option_list.highlighted = 1

            modal.action_open_selected_in_editor()
            await pilot.pause()

            assert pilot.app.screen is modal
            assert pilot.app.suspend_recorder.entered_count == 1

    assert run_calls == [(["test-editor", str(source_path)], False, True)]


async def test_xprompt_select_ctrl_e_from_filter_opens_without_dismissing(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "review.md"
    prompts = {"review": _source_workflow("review", str(source_path))}
    dismissed: list[object | None] = []
    run_calls: list[tuple[list[str], bool, bool]] = []

    def fake_run(args: list[str], *, check: bool) -> None:
        app = modal.app
        run_calls.append((args, check, app.suspend_recorder.active))

    with (
        patch(
            "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
            return_value=prompts,
        ),
        patch.dict("os.environ", {"EDITOR": "test-editor"}, clear=False),
        patch(
            "sase.ace.tui.modals.xprompt_select_modal.subprocess.run",
            side_effect=fake_run,
        ),
    ):
        modal = XPromptSelectModal()
        async with _TestApp().run_test() as pilot:
            pilot.app.push_screen(modal, callback=dismissed.append)
            await pilot.pause()

            await pilot.press("ctrl+e")
            await pilot.pause()

            assert pilot.app.screen is modal
            assert dismissed == []
            assert modal._selected_name() == "review"
            assert pilot.app.suspend_recorder.entered_count == 1

    assert run_calls == [(["test-editor", str(source_path)], False, True)]


async def test_xprompt_select_ctrl_e_warns_for_missing_source_path() -> None:
    prompts = {"review": _source_workflow("review", None)}

    with (
        patch(
            "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
            return_value=prompts,
        ),
        patch(
            "sase.ace.tui.modals.xprompt_select_modal.subprocess.run",
        ) as mock_run,
    ):
        modal = XPromptSelectModal()
        async with _TestApp().run_test() as pilot:
            pilot.app.push_screen(modal)
            await pilot.pause()

            await pilot.press("ctrl+e")
            await pilot.pause()

            assert pilot.app.screen is modal
            assert pilot.app.notifications == [
                ("Could not resolve source file path", "error")
            ]

    mock_run.assert_not_called()
