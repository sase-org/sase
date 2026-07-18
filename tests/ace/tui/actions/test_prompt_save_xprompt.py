"""Prompt-bar writes selected by the unified xprompt/snippet save panel."""

from __future__ import annotations

import asyncio
import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import yaml  # type: ignore[import-untyped]
from textual.app import App, ComposeResult

from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt import (
    PromptBarSaveXpromptMixin,
    _run_git_commit_push_sync,
)
from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git import (
    _is_index_lock_error,
)
from sase.ace.tui.modals import (
    ConfirmActionModal,
    UnifiedSaveLocation,
    UnifiedXPromptSaveModal,
    UnifiedXPromptSaveResult,
)
from sase.ace.tui.modals.xprompt_location_modal import XPromptLocation
from sase.ace.tui.widgets._prompt_input_bar_stack_actions import StashedPromptPane
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import SaveTargetFormat


class _SaveHarness(PromptBarSaveXpromptMixin):
    def __init__(self) -> None:
        self._prompt_context = None
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed: list[tuple[object, object]] = []
        self.git_offers: list[tuple[str, bool, str, str]] = []
        self._user_snippets: dict[str, str] = {}
        self._snippets_cache: dict[str, str] | None = None

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
        noun: str = "xprompt",
        commit_type: str = "xprompt",
    ) -> None:
        del commit_type
        self.git_offers.append((file_path, is_new, xprompt_name, noun))


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


class _SaveFlowApp(PromptBarSaveXpromptMixin, App[None]):
    """Exercise prompt dispatch and the real async save-panel boundary."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, initial_value: str) -> None:
        super().__init__()
        self._initial_value = initial_value
        self._prompt_context = None
        self._user_snippets: dict[str, str] = {}
        self._snippets_cache: dict[str, str] | None = None
        self.save_requests: list[PromptInputBar.SaveAsXpromptRequested] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value=self._initial_value)

    async def on_prompt_input_bar_save_as_xprompt_requested(
        self, event: PromptInputBar.SaveAsXpromptRequested
    ) -> None:
        self.save_requests.append(event)
        await super().on_prompt_input_bar_save_as_xprompt_requested(event)

    def _offer_git_commit(self, *_args: object, **_kwargs: object) -> None:
        pass


async def _wait_save_tasks(harness: object) -> None:
    tasks = list(getattr(harness, "_xprompt_save_async_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)


async def test_empty_save_request_toasts_noop() -> None:
    harness = _SaveHarness()
    await harness.on_prompt_input_bar_save_as_xprompt_requested(
        PromptInputBar.SaveAsXpromptRequested([])
    )
    await _wait_save_tasks(harness)
    assert harness.notifications == [("Nothing to save as an xprompt", "warning")]
    assert harness.pushed == []


async def test_request_opens_one_screen_with_active_pane_snippet_source() -> None:
    harness = _SaveHarness()
    with (
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
            return_value=[],
        ),
        patch("sase.xprompt.save_state.load_last_used_locations", return_value={}),
    ):
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [
                    StashedPromptPane(text="alpha", frontmatter=""),
                    StashedPromptPane(text="beta", frontmatter=""),
                ],
                snippet_body="beta",
            )
        )
        await _wait_save_tasks(harness)

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, UnifiedXPromptSaveModal)
    assert modal._body == "alpha\n---\nbeta"
    assert modal._snippet_body == "beta"
    assert modal._pane_count == 2


async def test_ctrl_g_ctrl_x_ctrl_x_opens_panel_in_snippet_mode(
    tmp_path: Path,
) -> None:
    xprompt_directory = tmp_path / "xprompts"
    xprompt_directory.mkdir()
    snippet_config = tmp_path / "sase.yml"
    snippet_config.write_text("ace:\n  snippets: {}\n", encoding="utf-8")
    xprompt_location = UnifiedSaveLocation(
        location=XPromptLocation("Xprompts", str(xprompt_directory), "directory"),
        group="CWD directories",
        display_path=str(xprompt_directory),
        names=frozenset(),
    )
    snippet_location = UnifiedSaveLocation(
        location=XPromptLocation("Snippets", str(snippet_config), "config"),
        group="Config files",
        display_path=str(snippet_config),
        names=frozenset(),
    )
    app = _SaveFlowApp("draft to reuse")

    with (
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
            return_value=[xprompt_location],
        ),
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
            return_value=[snippet_location],
        ),
        patch("sase.xprompt.save_state.load_last_used_locations", return_value={}),
    ):
        async with app.run_test(size=(105, 36)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            text_area = bar.active_text_area()

            await pilot.press("ctrl+g", "ctrl+x")
            for _ in range(20):
                await pilot.pause()
                if isinstance(app.screen, UnifiedXPromptSaveModal):
                    break

            modal = app.screen
            assert isinstance(modal, UnifiedXPromptSaveModal)
            assert len(app.save_requests) == 1
            assert bar.all_prompt_texts() == ["draft to reuse"]
            assert text_area._insert_g_prefix_pending is False
            assert bar._g_prefix_hints_visible is False

            await pilot.press("ctrl+x")
            assert modal._mode == "snippet"
            assert bar.all_prompt_texts() == ["draft to reuse"]

    # Opening and toggling the deterministic panel never writes either target.
    assert list(xprompt_directory.iterdir()) == []
    assert snippet_config.read_text(encoding="utf-8") == "ace:\n  snippets: {}\n"


async def test_save_request_returns_while_location_reads_are_stuck() -> None:
    harness = _SaveHarness()
    entered = threading.Event()
    release = threading.Event()

    def _slow_locations(*_args: object) -> list[object]:
        entered.set()
        release.wait(timeout=1.0)
        return []

    def _slow_last_used() -> dict[str, str]:
        entered.set()
        release.wait(timeout=1.0)
        return {}

    try:
        with (
            patch(
                "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
                side_effect=_slow_locations,
            ),
            patch(
                "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
                side_effect=_slow_locations,
            ),
            patch(
                "sase.xprompt.save_state.load_last_used_locations",
                side_effect=_slow_last_used,
            ),
        ):
            await asyncio.wait_for(
                harness.on_prompt_input_bar_save_as_xprompt_requested(
                    PromptInputBar.SaveAsXpromptRequested(
                        [StashedPromptPane(text="draft")]
                    )
                ),
                timeout=0.05,
            )
            await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=0.5)
            heartbeat = asyncio.Event()
            asyncio.get_running_loop().call_soon(heartbeat.set)
            await asyncio.wait_for(heartbeat.wait(), timeout=0.05)
    finally:
        release.set()
        await _wait_save_tasks(harness)


async def test_unified_markdown_result_writes_typed_name_authoritatively(
    tmp_path: Path,
) -> None:
    harness = _SaveHarness()
    target = UnifiedXPromptSaveResult(
        mode="xprompt",
        name="ns/foo",
        path=str(tmp_path / "ns_foo.md"),
        location_path=str(tmp_path),
        target_format=SaveTargetFormat.MARKDOWN,
        entry_name=None,
        display_path="./ns_foo.md",
        exists=False,
        frontmatter=PromptFrontmatter(name="ns/foo", description="Saved"),
    )
    with patch("sase.xprompt.save_state.save_last_used_location", return_value=True):
        await harness._write_xprompt_target(target, "new body")

    written = Path(target.path).read_text(encoding="utf-8")
    assert "name: ns/foo" in written
    assert "description: Saved" in written
    assert written.endswith("new body\n")
    assert harness.notifications == [("Created xprompt 'ns/foo'", None)]
    assert harness.git_offers == [(target.path, True, "ns/foo", "xprompt")]


async def test_unified_config_result_inserts_xprompt(tmp_path: Path) -> None:
    config = tmp_path / "sase" / "sase.yml"
    config.parent.mkdir()
    config.write_text("theme: dark\n", encoding="utf-8")
    harness = _SaveHarness()
    target = UnifiedXPromptSaveResult(
        mode="xprompt",
        name="review",
        path=str(config),
        location_path=str(config),
        target_format=SaveTargetFormat.CONFIG,
        entry_name="review",
        display_path="./sase/sase.yml",
        exists=False,
        frontmatter=PromptFrontmatter(description="Review code"),
    )
    with patch("sase.xprompt.save_state.save_last_used_location", return_value=True):
        await harness._write_xprompt_target(target, "check this")

    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert payload["xprompts"]["review"] == {
        "description": "Review code",
        "content": "check this",
    }


async def test_unified_snippet_result_writes_only_active_pane_and_refreshes(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase" / "sase.yml"
    config.parent.mkdir()
    config.write_text("ace:\n  snippets: {}\n", encoding="utf-8")
    harness = _SaveHarness()
    target = UnifiedXPromptSaveResult(
        mode="snippet",
        name="review",
        path=str(config),
        location_path=str(config),
        target_format=None,
        entry_name="review",
        display_path="./sase/sase.yml",
        exists=False,
        frontmatter=PromptFrontmatter(),
    )

    def merged() -> dict[str, object]:
        return yaml.safe_load(config.read_text(encoding="utf-8"))

    with (
        patch("sase.xprompt.save_state.save_last_used_location", return_value=True),
        patch("sase.config.load_merged_config", side_effect=merged),
    ):
        await harness._write_snippet_target(target, "beta")

    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert payload["ace"]["snippets"] == {"review": "beta"}
    assert harness._user_snippets == {"review": "beta"}
    assert harness.git_offers == [(str(config), True, "review", "snippet")]


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
    ):
        harness._offer_git_commit(str(path), is_new=True, xprompt_name="review")
        confirm, callback = harness.pushed[0]
        assert isinstance(confirm, ConfirmActionModal)
        assert callable(callback)
        callback(True)
    assert len(harness.submitted) == 1
    args, kwargs = harness.submitted[0]
    assert args[:3] == ("xprompt-commit", "xprompts/review.md", str(tmp_path))
    assert kwargs["dedup_key"] == f"xprompt-commit:{tmp_path}:xprompts/review.md"


def test_git_commit_push_worker_runs_git_sequence(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    path = tmp_path / "review.md"
    with (
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
            side_effect=run,
        ),
        patch("sase.config.get_use_chezmoi", return_value=False),
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )

    assert result.success is True
    assert calls[-3:] == [
        ["git", "-C", str(tmp_path), "commit", "-m", "chore: Add xprompt review"],
        ["git", "-C", str(tmp_path), "pull", "--rebase"],
        ["git", "-C", str(tmp_path), "push"],
    ]


def test_git_commit_push_worker_stops_on_add_failure(tmp_path: Path) -> None:
    path = tmp_path / "review.md"
    with patch(
        "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
        return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="pathspec"),
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )
    assert result.success is False
    assert result.message == "Git add failed: pathspec"


def test_git_commit_push_worker_retries_after_removing_index_lock(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    commit_attempts = 0

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal commit_attempts
        if argv[3] == "commit":
            commit_attempts += 1
            if commit_attempts == 1:
                return subprocess.CompletedProcess(
                    argv,
                    128,
                    stdout="",
                    stderr=f"fatal: Unable to create '{lock}': File exists.",
                )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    with (
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
            side_effect=run,
        ),
        patch("sase.config.get_use_chezmoi", return_value=False),
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(tmp_path / "review.md"),
            commit_message="chore: Add xprompt review",
        )
    assert result.success
    assert result.index_lock_removed
    assert commit_attempts == 2
    assert not lock.exists()


def test_is_index_lock_error_detects_git_lock_path() -> None:
    assert _is_index_lock_error(
        "fatal: Unable to create '/repo/.git/index.lock': File exists."
    )
    assert not _is_index_lock_error("fatal: unable to auto-detect email address")
