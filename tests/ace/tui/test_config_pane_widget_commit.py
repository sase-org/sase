"""Post-edit notification and commit tests for the Config pane widget."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git import (
    GitCommitPushResult,
)
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_commit import ConfigCommitOffer
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.config.edit import AppliedResult
from tests.ace.tui._config_pane_widget_helpers import (
    _open_config_pane,
    _patch_loaders,
)


def _config_applied(path: str = "/repo/sase.yml") -> AppliedResult:
    return AppliedResult(
        path=path,
        op="set",
        key_path=("timezone",),
        created=False,
        used_chezmoi=True,
    )


def _config_offer() -> ConfigCommitOffer:
    return ConfigCommitOffer(
        git_root="/repo",
        file_path="/repo/home/dot_config/sase/sase.yml",
        rel_path="home/dot_config/sase/sase.yml",
        message="chore: Update config timezone\n\nSASE_TYPE=config",
    )


async def test_config_pane_successful_write_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        events: list[str] = []
        monkeypatch.setattr(
            page.app, "notify", lambda message, **_kw: events.append(message)
        )
        monkeypatch.setattr(pane, "action_refresh", lambda: events.append("refresh"))

        def discover(*_args: Any, **_kwargs: Any) -> None:
            events.append("discover")
            return None

        monkeypatch.setattr(cp, "_build_config_commit_offer", discover)
        pane._on_edit_dismissed(
            AppliedResult(
                path="/tmp/sase.yml",
                op="set",
                key_path=("timezone",),
                created=False,
                used_chezmoi=True,
            )
        )

        assert events[:2] == [
            "wrote timezone → /tmp/sase.yml (chezmoi applied)",
            "refresh",
        ]
        await page.wait_for(lambda _s: "discover" in events)


async def test_config_pane_dirty_source_uses_canonical_commit_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    offer = _config_offer()
    monkeypatch.setattr(cp, "_build_config_commit_offer", lambda *_a, **_kw: offer)

    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._on_edit_dismissed(_config_applied(offer.file_path))
        await page.expect_modal("ConfirmActionModal")

        modal = page.app.screen
        assert isinstance(modal, ConfirmActionModal)
        assert modal._title == "Commit & Push"
        assert modal._message == "Commit and push your config field change?"
        assert modal._subject == offer.rel_path
        assert modal._icon == "↑"
        assert modal._confirm_label == "Commit & push"
        assert modal._cancel_label == "Skip"
        assert modal._default == "confirm"


async def test_config_pane_declining_or_dismissing_commit_submits_no_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    offer = _config_offer()
    monkeypatch.setattr(cp, "_build_config_commit_offer", lambda *_a, **_kw: offer)

    async with AcePage() as page:
        pane = await _open_config_pane(page)
        submit = MagicMock()
        monkeypatch.setattr(page.app, "_submit_tracked_task", submit)

        for key in ("n", "escape"):
            pane._on_edit_dismissed(_config_applied(offer.file_path))
            await page.expect_modal("ConfirmActionModal")
            await page.press(key)
            await page.expect_modal("ConfigCenterModal")

        submit.assert_not_called()


async def test_config_pane_confirm_submits_actual_written_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    offer = _config_offer()
    monkeypatch.setattr(cp, "_build_config_commit_offer", lambda *_a, **_kw: offer)
    run = MagicMock(
        return_value=GitCommitPushResult(True, "Committed and pushed to remote")
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git.run_git_commit_push_sync",
        run,
    )

    async with AcePage() as page:
        pane = await _open_config_pane(page)
        submit = MagicMock()
        monkeypatch.setattr(page.app, "_submit_tracked_task", submit)
        pane._on_edit_dismissed(_config_applied(offer.file_path))
        await page.expect_modal("ConfirmActionModal")
        await page.press("y")
        await page.wait_for(lambda _s: submit.call_count == 1)

        args, kwargs = submit.call_args
        assert args[:3] == ("config-commit", offer.rel_path, offer.git_root)
        assert kwargs["display_name"] == f"commit config {offer.rel_path}"
        assert kwargs["dedup_key"] == (
            f"config-commit:{offer.git_root}:{offer.rel_path}"
        )
        assert kwargs["reload_on_complete"] is False
        assert kwargs["notify_on_complete"] is False

        task_result = args[3]()
        assert task_result.success is True
        run.assert_called_once_with(
            git_root=offer.git_root,
            file_path=offer.file_path,
            commit_message=offer.message,
        )


async def test_config_pane_cancelled_failed_clean_and_non_git_skip_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)

        # Both cancellation and a write/apply failure dismiss the editor with None.
        pane._on_edit_dismissed(None)
        pane._on_edit_dismissed(_config_applied("/tmp/clean-or-non-git.yml"))
        await page.pause()

        assert isinstance(page.app.screen, ConfigCenterModal)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            GitCommitPushResult(True, "Committed and pushed to remote"),
            [("Committed and pushed to remote", "information")],
        ),
        (
            GitCommitPushResult(False, "Push failed: rejected"),
            [("Push failed: rejected", "error")],
        ),
        (
            GitCommitPushResult(
                True,
                "Committed and pushed to remote",
                index_lock_removed=True,
            ),
            [
                ("Committed and pushed to remote", "information"),
                (
                    "Removed a stale git index.lock in repo and retried the commit.",
                    "warning",
                ),
            ],
        ),
    ],
)
async def test_config_pane_commit_task_reports_established_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    result: GitCommitPushResult,
    expected: list[tuple[str, str]],
) -> None:
    _patch_loaders(monkeypatch)
    offer = _config_offer()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git.run_git_commit_push_sync",
        lambda **_kw: result,
    )

    async with AcePage() as page:
        pane = await _open_config_pane(page)
        submit = MagicMock()
        notifications: list[tuple[str, str]] = []
        monkeypatch.setattr(page.app, "_submit_tracked_task", submit)
        monkeypatch.setattr(
            page.app,
            "notify",
            lambda message, *, severity="information", **_kw: notifications.append(
                (message, severity)
            ),
        )

        pane._submit_commit_task(offer)
        args, kwargs = submit.call_args
        task_result = args[3]()
        kwargs["on_complete"](
            SimpleNamespace(
                success=task_result.success,
                message=task_result.message,
                payload=task_result.payload,
            )
        )

        assert notifications == expected


async def test_config_pane_successful_write_toast_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        messages: list[str] = []
        monkeypatch.setattr(
            page.app, "notify", lambda message, **_kw: messages.append(message)
        )
        monkeypatch.setattr(pane, "action_refresh", lambda: None)
        pane._on_edit_dismissed(
            AppliedResult(
                path="/tmp/sase.yml",
                op="set",
                key_path=("timezone",),
                created=False,
                used_chezmoi=True,
            )
        )
        assert messages == ["wrote timezone → /tmp/sase.yml (chezmoi applied)"]


async def test_config_pane_runner_limit_write_requests_standard_agents_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        refresh_sources: list[str] = []
        monkeypatch.setattr(page.app, "notify", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(pane, "action_refresh", lambda: None)
        monkeypatch.setattr(
            page.app,
            "request_agents_refresh",
            lambda source: refresh_sources.append(source),
        )

        pane._on_edit_dismissed(
            AppliedResult(
                path="/tmp/sase.yml",
                op="set",
                key_path=("max_running_agents",),
                created=False,
                used_chezmoi=False,
            )
        )

        assert refresh_sources == ["config"]
