from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.modals.xprompt_save_target_modal import (
    XPromptSaveTarget,
    XPromptSaveTargetModal,
    _XPromptSaveRow,
    _load_xprompt_save_rows,
)
from sase.xprompt.save import SaveTargetFormat
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def test_load_save_rows_excludes_workflows_and_marks_eligible_targets(
    tmp_path: Path,
) -> None:
    md_path = tmp_path / "review.md"
    md_path.write_text("review", encoding="utf-8")
    cfg_path = tmp_path / "sase.yml"
    cfg_path.write_text("xprompts:\n  cfg: cfg body\n", encoding="utf-8")

    prompts = {
        "review": Workflow(
            name="review",
            steps=[WorkflowStep(name="main", prompt_part="body")],
            source_path=str(md_path),
        ),
        "cfg": Workflow(
            name="cfg",
            steps=[WorkflowStep(name="main", prompt_part="body")],
            source_path="config",
        ),
        "workflow": Workflow(
            name="workflow",
            steps=[WorkflowStep(name="run", agent="do it")],
            source_path=str(tmp_path / "workflow.yml"),
        ),
    }

    with (
        patch(
            "sase.ace.tui.modals.xprompt_save_target_modal.get_all_prompts",
            return_value=prompts,
        ),
        patch(
            "sase.ace.tui.modals.xprompt_save_target_modal."
            "get_all_project_local_prompts",
            return_value={},
        ),
        patch(
            "sase.ace.tui.modals.xprompt_save_target_modal.resolve_source_to_file_path",
            side_effect=lambda source: str(cfg_path) if source == "config" else source,
        ),
    ):
        rows = _load_xprompt_save_rows()

    by_name = {row.name: row for row in rows}
    assert by_name["review"].target is not None
    assert by_name["review"].target.target_format == SaveTargetFormat.MARKDOWN
    assert by_name["cfg"].target is not None
    assert by_name["cfg"].target.target_format == SaveTargetFormat.CONFIG
    assert by_name["cfg"].target.entry_name == "cfg"
    assert "workflow" not in by_name


class _SaveTargetApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, modal: XPromptSaveTargetModal) -> None:
        super().__init__()
        self._modal = modal
        self.result: XPromptSaveTarget | None = None

    def compose(self) -> ComposeResult:
        yield OptionList(id="placeholder")

    def on_mount(self) -> None:
        self.push_screen(self._modal, self._on_result)

    def _on_result(self, result: XPromptSaveTarget | None) -> None:
        self.result = result


async def test_create_new_is_pinned_first_and_selectable() -> None:
    row = _XPromptSaveRow(
        name="review",
        workflow=Workflow(
            name="review",
            steps=[WorkflowStep(name="main", prompt_part="body")],
        ),
        source_category="User sase.yml",
        source_path="config",
        display_path="~/.config/sase/sase.yml",
        target=XPromptSaveTarget(
            kind="overwrite",
            name="review",
            path="/tmp/sase.yml",
            target_format=SaveTargetFormat.CONFIG,
            entry_name="review",
        ),
    )
    app = _SaveTargetApp(XPromptSaveTargetModal([row], pane_count=1))

    async with app.run_test(size=(100, 32)) as pilot:
        modal = app.screen
        assert isinstance(modal, XPromptSaveTargetModal)
        option_list = modal.query_one("#save-target-list", OptionList)
        assert option_list.get_option_at_index(0).id == "__create__"
        assert option_list.highlighted == 0

        await pilot.press("enter")
        await pilot.pause()

    assert app.result == XPromptSaveTarget(kind="create")


async def test_create_snippet_option_hidden_when_not_allowed() -> None:
    app = _SaveTargetApp(XPromptSaveTargetModal([], pane_count=1))

    async with app.run_test(size=(100, 32)) as pilot:
        modal = app.screen
        assert isinstance(modal, XPromptSaveTargetModal)
        option_list = modal.query_one("#save-target-list", OptionList)
        ids = [
            option_list.get_option_at_index(i).id
            for i in range(option_list.option_count)
        ]
        assert "__create_snippet__" not in ids
        await pilot.pause()


async def test_create_snippet_option_shown_and_selectable_when_allowed() -> None:
    app = _SaveTargetApp(
        XPromptSaveTargetModal([], pane_count=1, allow_create_snippet=True)
    )

    async with app.run_test(size=(100, 32)) as pilot:
        modal = app.screen
        assert isinstance(modal, XPromptSaveTargetModal)
        option_list = modal.query_one("#save-target-list", OptionList)
        assert option_list.get_option_at_index(0).id == "__create__"
        assert option_list.get_option_at_index(1).id == "__create_snippet__"

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert option_list.highlighted == 1
        await pilot.press("enter")
        await pilot.pause()

    assert app.result == XPromptSaveTarget(kind="create_snippet")


def test_snippet_preview_notes_current_pane_for_multi_pane_draft() -> None:
    modal = XPromptSaveTargetModal([], pane_count=3, allow_create_snippet=True)
    preview = modal._create_snippet_preview()
    assert "current pane only" in preview
    assert "3 panes" in preview


def test_snippet_preview_describes_single_pane_source() -> None:
    modal = XPromptSaveTargetModal([], pane_count=1, allow_create_snippet=True)
    preview = modal._create_snippet_preview()
    assert "the current prompt pane." in preview
    assert "panes in the draft" not in preview


async def test_disabled_rows_are_skipped_by_navigation() -> None:
    disabled = _XPromptSaveRow(
        name="read_only",
        workflow=Workflow(
            name="read_only",
            steps=[WorkflowStep(name="main", prompt_part="body")],
        ),
        source_category="User sase.yml",
        source_path="config",
        display_path="~/.config/sase/sase.yml",
        target=None,
        disabled_reason="source file is read-only",
    )
    selectable = _XPromptSaveRow(
        name="review",
        workflow=Workflow(
            name="review",
            steps=[WorkflowStep(name="main", prompt_part="body")],
        ),
        source_category="User sase.yml",
        source_path="config",
        display_path="~/.config/sase/sase.yml",
        target=XPromptSaveTarget(
            kind="overwrite",
            name="review",
            path="/tmp/sase.yml",
            target_format=SaveTargetFormat.CONFIG,
            entry_name="review",
        ),
    )
    app = _SaveTargetApp(XPromptSaveTargetModal([disabled, selectable], pane_count=1))

    async with app.run_test(size=(100, 32)) as pilot:
        modal = app.screen
        assert isinstance(modal, XPromptSaveTargetModal)
        option_list = modal.query_one("#save-target-list", OptionList)

        await pilot.press("ctrl+n")
        await pilot.pause()

        highlighted = option_list.highlighted
        assert highlighted is not None
        assert option_list.get_option_at_index(highlighted).id == "row__1"
