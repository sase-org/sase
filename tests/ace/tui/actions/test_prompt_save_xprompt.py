from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt import (
    PromptBarSaveXpromptMixin,
)
from sase.ace.tui.modals import ConfirmActionModal, XPromptSaveTargetModal
from sase.ace.tui.modals.xprompt_save_target_modal import (
    XPromptSaveTarget,
    _XPromptSaveRow,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_actions import StashedPromptPane
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.save import SaveTargetFormat
from sase.xprompt.workflow_models import Workflow, WorkflowStep


class _SaveHarness(PromptBarSaveXpromptMixin):
    def __init__(self) -> None:
        self._prompt_context = None
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed: list[tuple[object, object]] = []
        self.git_offers: list[tuple[str, bool, str]] = []

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed.append((screen, callback))

    def _offer_git_commit(
        self,
        file_path: str,
        *,
        is_new: bool,
        xprompt_name: str,
    ) -> None:
        self.git_offers.append((file_path, is_new, xprompt_name))


async def _wait_save_tasks(harness: object) -> None:
    tasks = list(getattr(harness, "_xprompt_save_async_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)


async def test_empty_save_as_xprompt_request_toasts_noop() -> None:
    harness = _SaveHarness()

    await harness.on_prompt_input_bar_save_as_xprompt_requested(
        PromptInputBar.SaveAsXpromptRequested([])
    )

    assert harness.notifications == [("Nothing to save as an xprompt", "warning")]
    assert harness.pushed == []


async def test_overwrite_target_confirms_then_writes_markdown(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.md"
    path.write_text("old", encoding="utf-8")
    target = XPromptSaveTarget(
        kind="overwrite",
        name="review",
        path=str(path),
        target_format=SaveTargetFormat.MARKDOWN,
        display_path=str(path),
    )
    row = _XPromptSaveRow(
        name="review",
        workflow=Workflow(
            name="review",
            steps=[WorkflowStep(name="main", prompt_part="old")],
        ),
        source_category="CWD xprompts/",
        source_path=str(path),
        display_path="./xprompts/review.md",
        target=target,
    )
    harness = _SaveHarness()

    with patch(
        "sase.ace.tui.modals.xprompt_save_target_modal.load_xprompt_save_rows",
        return_value=[row],
    ):
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [
                    StashedPromptPane(
                        text="new body",
                        frontmatter="---\ndescription: saved\n---",
                    )
                ]
            )
        )

    assert len(harness.pushed) == 1
    modal, on_target = harness.pushed[0]
    assert isinstance(modal, XPromptSaveTargetModal)
    assert callable(on_target)
    on_target(target)

    assert len(harness.pushed) == 2
    confirm, on_confirm = harness.pushed[1]
    assert isinstance(confirm, ConfirmActionModal)
    assert callable(on_confirm)
    on_confirm(True)
    await _wait_save_tasks(harness)

    text = path.read_text(encoding="utf-8")
    assert "description: saved" in text
    assert text.endswith("new body\n")
    assert harness.notifications == [("Saved draft as xprompt 'review'", None)]
    assert harness.git_offers == [(str(path), False, "review")]
