from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml  # type: ignore[import-untyped]

from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt import (
    PromptBarSaveXpromptMixin,
    _run_git_commit_push_sync,
)
from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git import (
    _is_index_lock_error,
)
from sase.ace.tui.modals import (
    ConfirmActionModal,
    SnippetConfigLocation,
    SnippetConfigLocationModal,
    SnippetNameModal,
    UnifiedXPromptSaveModal,
)
from sase.ace.tui.modals.xprompt_save_target_modal import XPromptSaveTarget
from sase.ace.tui.widgets._prompt_input_bar_stack_actions import StashedPromptPane
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.save import SaveTargetFormat


class _SaveHarness(PromptBarSaveXpromptMixin):
    def __init__(self) -> None:
        self._prompt_context = None
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed: list[tuple[object, object]] = []
        self.git_offers: list[tuple[str, bool, str]] = []
        self.git_offer_nouns: list[str] = []
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
        self.git_offers.append((file_path, is_new, xprompt_name))
        self.git_offer_nouns.append(noun)

    def get_snippets(self) -> dict[str, str]:
        cached = self._snippets_cache
        if cached is not None:
            return cached
        from sase.xprompt.snippet_bridge import (
            _get_xprompt_snippets,
            resolve_snippet_references,
        )

        merged = _get_xprompt_snippets()
        merged.update(self._user_snippets)
        merged = resolve_snippet_references(merged)
        self._snippets_cache = merged
        return merged


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
    harness = _SaveHarness()

    with patch(
        "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
        return_value=[],
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
    assert isinstance(modal, UnifiedXPromptSaveModal)
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
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )

    assert result.success is True
    assert result.message == "Committed and pushed to remote"
    assert result.index_lock_removed is False
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
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )

    assert result.success is False
    assert result.message == "Git add failed: pathspec"
    assert result.index_lock_removed is False
    assert calls == [["git", "-C", str(tmp_path), "add", "--", str(path)]]


def test_git_commit_push_worker_retries_after_removing_index_lock(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    calls: list[list[str]] = []
    commit_attempts = 0

    def _run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal commit_attempts
        calls.append(argv)
        if argv[3] == "commit":
            commit_attempts += 1
            if commit_attempts == 1:
                return subprocess.CompletedProcess(
                    argv,
                    128,
                    stdout="",
                    stderr=(
                        f"fatal: Unable to create '{lock}': File exists.\n"
                        "Another git process seems to be running."
                    ),
                )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    path = tmp_path / "review.md"
    with (
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
            side_effect=_run,
        ),
        patch("sase.config.get_use_chezmoi", return_value=False),
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )

    assert result.success is True
    assert result.index_lock_removed is True
    assert result.message == "Committed and pushed to remote"
    assert not lock.exists()
    assert (
        calls.count(
            ["git", "-C", str(tmp_path), "commit", "-m", "chore: Add xprompt review"]
        )
        == 2
    )


def test_git_commit_push_worker_reports_lock_removed_when_retry_fails(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    calls: list[list[str]] = []
    commit_attempts = 0

    def _run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal commit_attempts
        calls.append(argv)
        if argv[3] == "commit":
            commit_attempts += 1
            if commit_attempts == 1:
                return subprocess.CompletedProcess(
                    argv,
                    128,
                    stdout="",
                    stderr=f"fatal: Unable to create '{lock}': File exists.",
                )
            return subprocess.CompletedProcess(
                argv,
                1,
                stdout="",
                stderr="commit still failed",
            )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    path = tmp_path / "review.md"
    with patch(
        "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
        side_effect=_run,
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )

    assert result.success is False
    assert result.index_lock_removed is True
    assert result.message == "Commit failed: commit still failed"
    assert not lock.exists()
    assert (
        calls.count(
            ["git", "-C", str(tmp_path), "commit", "-m", "chore: Add xprompt review"]
        )
        == 2
    )


def test_git_commit_push_worker_does_not_retry_lock_text_without_lock_file(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def _run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if argv[3] == "commit":
            return subprocess.CompletedProcess(
                argv,
                1,
                stdout="",
                stderr="fatal: failed while reading .git/index.lock metadata",
            )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    path = tmp_path / "review.md"
    with patch(
        "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt.subprocess.run",
        side_effect=_run,
    ):
        result = _run_git_commit_push_sync(
            git_root=str(tmp_path),
            file_path=str(path),
            commit_message="chore: Add xprompt review",
        )

    assert result.success is False
    assert result.index_lock_removed is False
    assert result.message == (
        "Commit failed: fatal: failed while reading .git/index.lock metadata"
    )
    assert calls == [
        ["git", "-C", str(tmp_path), "add", "--", str(path)],
        ["git", "-C", str(tmp_path), "commit", "-m", "chore: Add xprompt review"],
    ]


def test_is_index_lock_error_detects_git_lock_path() -> None:
    assert (
        _is_index_lock_error(
            "fatal: Unable to create '/repo/.git/index.lock': File exists."
        )
        is True
    )
    assert _is_index_lock_error("fatal: unable to auto-detect email address") is False


# --- save as snippet (Create a new snippet...) -----------------------------


def _patch_save_rows() -> object:
    return patch(
        "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
        return_value=[],
    )


async def test_single_pane_request_enables_snippet_option() -> None:
    harness = _SaveHarness()

    with _patch_save_rows():
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [StashedPromptPane(text="body", frontmatter="")],
                single_pane=True,
            )
        )

    modal, _on_target = harness.pushed[0]
    assert isinstance(modal, UnifiedXPromptSaveModal)
    assert modal._allow_create_snippet is True


async def test_multi_pane_request_enables_snippet_option() -> None:
    harness = _SaveHarness()

    with _patch_save_rows():
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [
                    StashedPromptPane(text="alpha", frontmatter=""),
                    StashedPromptPane(text="beta", frontmatter=""),
                ],
                single_pane=False,
                snippet_body="beta",
            )
        )

    modal, _on_target = harness.pushed[0]
    assert isinstance(modal, UnifiedXPromptSaveModal)
    # The snippet option is now always offered, even for multi-pane drafts.
    assert modal._allow_create_snippet is True


async def test_create_snippet_flow_writes_refreshes_and_offers_commit(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text(
        "ace:\n  snippets:\n    existing: |\n      old$0\n",
        encoding="utf-8",
    )
    location = SnippetConfigLocation(
        label="User sase.yml",
        path=str(config),
        display_path="~/.config/sase/sase.yml",
    )
    harness = _SaveHarness()

    def _fake_merged() -> dict[str, object]:
        return yaml.safe_load(config.read_text(encoding="utf-8")) or {}

    with (
        _patch_save_rows(),
        patch(
            "sase.ace.tui.modals.load_snippet_config_locations",
            return_value=[location],
        ),
        patch("sase.config.load_merged_config", _fake_merged),
        patch("sase.xprompt.snippet_bridge._get_xprompt_snippets", return_value={}),
    ):
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [StashedPromptPane(text="my prompt body", frontmatter="")],
                single_pane=True,
            )
        )

        assert len(harness.pushed) == 1
        target_modal, on_target = harness.pushed[0]
        assert isinstance(target_modal, UnifiedXPromptSaveModal)
        on_target(XPromptSaveTarget(kind="create_snippet"))
        await _wait_save_tasks(harness)

        assert len(harness.pushed) == 2
        config_modal, on_location = harness.pushed[1]
        assert isinstance(config_modal, SnippetConfigLocationModal)
        on_location(location)
        await _wait_save_tasks(harness)

        assert len(harness.pushed) == 3
        name_modal, on_name = harness.pushed[2]
        assert isinstance(name_modal, SnippetNameModal)
        # Existing names are loaded from the selected file only.
        assert name_modal._existing_names == {"existing"}
        on_name("foo")
        await _wait_save_tasks(harness)

    written = config.read_text(encoding="utf-8")
    assert "    foo: |-\n      my prompt body\n" in written
    # ``|-`` strips the trailing newline, so the freshly written snippet loads
    # as exactly the active-pane body; the untouched ``existing`` entry keeps
    # its ``|`` round-tripped newline.
    assert _snippets_of(written) == {"existing": "old$0\n", "foo": "my prompt body"}

    assert (
        "Created snippet 'foo' in ~/.config/sase/sase.yml",
        None,
    ) in harness.notifications
    assert harness.git_offers == [(str(config), True, "foo")]
    assert harness.git_offer_nouns == ["snippet"]

    # Cache refreshed: user snippets reloaded, resolved cache dropped.
    assert harness._user_snippets["foo"] == "my prompt body"
    assert harness._snippets_cache is None
    assert harness.get_snippets()["foo"] == "my prompt body"


async def test_create_snippet_same_name_overwrites_without_confirmation(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text(
        "ace:\n  snippets:\n    foo: |\n      old body$0\n",
        encoding="utf-8",
    )
    location = SnippetConfigLocation(
        label="Local sase.yml",
        path=str(config),
        display_path="./sase.yml",
    )
    harness = _SaveHarness()

    def _fake_merged() -> dict[str, object]:
        return yaml.safe_load(config.read_text(encoding="utf-8")) or {}

    with (
        _patch_save_rows(),
        patch(
            "sase.ace.tui.modals.load_snippet_config_locations",
            return_value=[location],
        ),
        patch("sase.config.load_merged_config", _fake_merged),
        patch("sase.xprompt.snippet_bridge._get_xprompt_snippets", return_value={}),
    ):
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [StashedPromptPane(text="new body", frontmatter="")],
                single_pane=True,
            )
        )
        _target_modal, on_target = harness.pushed[0]
        on_target(XPromptSaveTarget(kind="create_snippet"))
        await _wait_save_tasks(harness)
        _config_modal, on_location = harness.pushed[1]
        on_location(location)
        await _wait_save_tasks(harness)
        name_modal, on_name = harness.pushed[2]
        assert isinstance(name_modal, SnippetNameModal)
        on_name("foo")
        await _wait_save_tasks(harness)

    # No confirm modal pushed for the overwrite; the only screens are the
    # target picker, config selector, and name modal.
    assert len(harness.pushed) == 3
    assert _snippets_of(config.read_text(encoding="utf-8")) == {"foo": "new body"}


async def test_create_snippet_flow_multi_pane_writes_only_active_pane(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text(
        "ace:\n  snippets:\n    existing: |\n      old$0\n",
        encoding="utf-8",
    )
    location = SnippetConfigLocation(
        label="User sase.yml",
        path=str(config),
        display_path="~/.config/sase/sase.yml",
    )
    harness = _SaveHarness()

    def _fake_merged() -> dict[str, object]:
        return yaml.safe_load(config.read_text(encoding="utf-8")) or {}

    with (
        _patch_save_rows(),
        patch(
            "sase.ace.tui.modals.load_snippet_config_locations",
            return_value=[location],
        ),
        patch("sase.config.load_merged_config", _fake_merged),
        patch("sase.xprompt.snippet_bridge._get_xprompt_snippets", return_value={}),
    ):
        # Multi-pane draft: the xprompt body joins both panes, but ``snippet_body``
        # carries only the active pane ("beta").
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [
                    StashedPromptPane(text="alpha", frontmatter=""),
                    StashedPromptPane(text="beta", frontmatter=""),
                ],
                single_pane=False,
                snippet_body="beta",
            )
        )
        _target_modal, on_target = harness.pushed[0]
        on_target(XPromptSaveTarget(kind="create_snippet"))
        await _wait_save_tasks(harness)
        _config_modal, on_location = harness.pushed[1]
        on_location(location)
        await _wait_save_tasks(harness)
        name_modal, on_name = harness.pushed[2]
        assert isinstance(name_modal, SnippetNameModal)
        on_name("multi")
        await _wait_save_tasks(harness)

    written = config.read_text(encoding="utf-8")
    # Only the active-pane body is written, never the ``\n---\n``-joined body.
    assert _snippets_of(written) == {"existing": "old$0\n", "multi": "beta"}
    assert "alpha" not in written
    assert "---" not in written


async def test_blank_snippet_body_selection_warns_and_skips_flow() -> None:
    harness = _SaveHarness()

    with _patch_save_rows():
        # Frontmatter-only draft: the xprompt body is empty and the active pane
        # carries no text, so the snippet source is blank.
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [StashedPromptPane(text="", frontmatter="---\ndescription: fm\n---")],
                single_pane=True,
                snippet_body="",
            )
        )

        assert len(harness.pushed) == 1
        _target_modal, on_target = harness.pushed[0]
        on_target(XPromptSaveTarget(kind="create_snippet"))
        await _wait_save_tasks(harness)

    # No config/name modal pushed; the user is warned instead.
    assert len(harness.pushed) == 1
    assert (
        "Current prompt pane is empty - nothing to save as a snippet",
        "warning",
    ) in harness.notifications


def _snippets_of(text: str) -> dict[str, str]:
    data = yaml.safe_load(text)
    return data["ace"]["snippets"]
