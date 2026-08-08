"""Tests for the ACE xprompt selection modal."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from textual.app import App
from textual.widgets import Input, OptionList

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


def _xprompt_swarm_workflow(name: str) -> Workflow:
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
        "multi": _xprompt_swarm_workflow("multi"),
        "sync": _standalone_workflow("sync"),
    }
    with patch(
        "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
        return_value=prompts,
    ):
        modal = XPromptSelectModal()

    assert modal._insertion_suffix("commit") == "commit"
    assert modal._insertion_suffix("multi") == "multi"
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


def test_xprompt_select_labels_and_previews_memory_entries() -> None:
    prompts = {
        "memory/glossary": Workflow(
            name="memory/glossary",
            description="Glossary terms.",
            memory_type="long",
            steps=[WorkflowStep(name="prompt", prompt_part="Memory body")],
        )
    }
    with patch(
        "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
        return_value=prompts,
    ):
        modal = XPromptSelectModal()

    label = modal._create_styled_label("memory/glossary")
    assert label.plain == "#memory/glossary  memory · long"
    preview = modal._all_items["memory/glossary"][0]
    assert "# Memory: memory/glossary" in preview
    assert "memory type: long" in preview


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


def _modal_with_expand(
    prompts: dict[str, Workflow],
    expand: object,
) -> XPromptSelectModal:
    with patch(
        "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
        return_value=prompts,
    ):
        return XPromptSelectModal(expand_callback=expand)  # type: ignore[arg-type]


async def test_xprompt_select_ctrl_i_expands_and_dismisses_without_insertion() -> None:
    prompts = {"commit": _simple_workflow("commit")}
    calls: list[tuple[str, Workflow]] = []

    def expand(name: str, workflow: Workflow) -> str | None:
        calls.append((name, workflow))
        return None  # success

    modal = _modal_with_expand(prompts, expand)
    dismissed: list[object | None] = []
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        await pilot.press("ctrl+i")
        await pilot.pause()

        # Callback ran with the highlighted entry, the modal dismissed, and the
        # dismiss payload is ``None`` so the normal insertion callback is a no-op.
        assert calls == [("commit", prompts["commit"])]
        assert pilot.app.screen is not modal
        assert dismissed == [None]


async def test_xprompt_select_ctrl_i_error_notifies_and_keeps_modal_open() -> None:
    prompts = {
        "alpha": _simple_workflow("alpha"),
        "beta": _simple_workflow("beta"),
    }
    error = "Cannot inline-expand #beta because it has workflow steps."

    def expand(_name: str, _workflow: Workflow) -> str | None:
        return error

    modal = _modal_with_expand(prompts, expand)
    dismissed: list[object | None] = []
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        option_list = modal.query_one("#xprompt-list", OptionList)
        option_list.highlighted = 1

        await pilot.press("ctrl+i")
        await pilot.pause()

        # Error keeps the modal open, surfaces an error notification, and leaves
        # the filter/highlight state untouched for another attempt.
        assert pilot.app.screen is modal
        assert dismissed == []
        assert pilot.app.notifications == [(error, "error")]
        assert option_list.highlighted == 1
        assert modal._filtered_names == ["alpha", "beta"]
        assert modal._selected_name() == "beta"


async def test_xprompt_select_ctrl_i_from_option_list_focus() -> None:
    prompts = {"commit": _simple_workflow("commit")}
    calls: list[str] = []

    def expand(name: str, _workflow: Workflow) -> str | None:
        calls.append(name)
        return None

    modal = _modal_with_expand(prompts, expand)
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.query_one("#xprompt-list", OptionList).focus()
        await pilot.pause()

        await pilot.press("ctrl+i")
        await pilot.pause()

        assert calls == ["commit"]


async def test_xprompt_select_tab_routes_to_expand_exactly_once() -> None:
    # ``Ctrl+I`` arrives as a Tab byte in real terminals; the modal must route
    # Tab to expansion without double-firing alongside the ``ctrl+i`` binding.
    prompts = {"commit": _simple_workflow("commit")}
    calls: list[str] = []

    def expand(name: str, _workflow: Workflow) -> str | None:
        calls.append(name)
        return None

    modal = _modal_with_expand(prompts, expand)
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()

        assert calls == ["commit"]


async def test_xprompt_select_ctrl_i_with_no_matches_warns() -> None:
    prompts = {"commit": _simple_workflow("commit")}
    calls: list[str] = []

    def expand(name: str, _workflow: Workflow) -> str | None:
        calls.append(name)
        return None

    modal = _modal_with_expand(prompts, expand)
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#xprompt-filter-input", Input)
        filter_input.value = "no-such-xprompt"
        await pilot.pause()

        await pilot.press("ctrl+i")
        await pilot.pause()

        # No selectable entry: warn, keep the modal open, never call the callback.
        assert calls == []
        assert pilot.app.screen is modal
        assert pilot.app.notifications == [("No xprompt selected", "warning")]


async def test_xprompt_select_ctrl_i_without_callback_is_noop() -> None:
    prompts = {"commit": _simple_workflow("commit")}
    with patch(
        "sase.ace.tui.modals.xprompt_select_modal.get_all_prompts",
        return_value=prompts,
    ):
        modal = XPromptSelectModal()  # no expand_callback wired

    dismissed: list[object | None] = []
    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        await pilot.press("ctrl+i")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert dismissed == []
        assert pilot.app.notifications == []
