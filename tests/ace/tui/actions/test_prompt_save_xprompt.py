from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt import (
    PromptBarSaveXpromptMixin,
    _run_git_commit_push_sync,
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


class _CommitHarness(PromptBarSaveXpromptMixin):
    def __init__(self) -> None:
        self._prompt_context = None
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed: list[tuple[object, object]] = []
        self.submitted: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed.append((screen, callback))

    def _submit_tracked_task(self, *args: object, **kwargs: object) -> object:
        self.submitted.append((args, kwargs))
        return object()


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


def test_commit_push_confirmation_submits_tracked_task(tmp_path: Path) -> None:
    path = tmp_path / "xprompts" / "review.md"
    path.parent.mkdir()
    path.write_text("body", encoding="utf-8")
    harness = _CommitHarness()

    with (
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.get_git_root",
            return_value=str(tmp_path),
        ),
        patch(
            "sase.ace.tui.modals.xprompt_browser_helpers.has_git_changes",
            return_value=True,
        ),
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
            side_effect=AssertionError("subprocess should run in the tracked task"),
        ),
    ):
        harness._offer_git_commit(str(path), is_new=True, xprompt_name="review")
        assert len(harness.pushed) == 1
        confirm, on_confirm = harness.pushed[0]
        assert isinstance(confirm, ConfirmActionModal)
        assert callable(on_confirm)
        on_confirm(True)

    assert len(harness.submitted) == 1
    args, kwargs = harness.submitted[0]
    assert args[:3] == ("xprompt-commit", "xprompts/review.md", str(tmp_path))
    assert kwargs["display_name"] == "commit xprompt xprompts/review.md"
    assert kwargs["dedup_key"] == f"xprompt-commit:{tmp_path}:xprompts/review.md"
    assert kwargs["reload_on_complete"] is False
    assert kwargs["notify_on_complete"] is False
    assert harness.notifications == []


def test_git_commit_push_worker_runs_git_sequence(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def _run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    path = tmp_path / "review.md"
    with (
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
            side_effect=_run,
        ),
        patch("sase.config.get_use_chezmoi", return_value=False),
    ):
        success, message = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )

    assert success is True
    assert message == "Committed and pushed to remote"
    assert calls == [
        ["git", "-C", str(tmp_path), "add", "--", str(path)],
        ["git", "-C", str(tmp_path), "commit", "-m", "chore: Add xprompt review"],
        ["git", "-C", str(tmp_path), "pull", "--rebase"],
        ["git", "-C", str(tmp_path), "push"],
    ]


def test_git_commit_push_worker_stops_on_add_failure(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def _run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="pathspec")

    path = tmp_path / "review.md"
    with patch(
        "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
        side_effect=_run,
    ):
        success, message = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )

    assert success is False
    assert message == "Git add failed: pathspec"
    assert calls == [["git", "-C", str(tmp_path), "add", "--", str(path)]]
