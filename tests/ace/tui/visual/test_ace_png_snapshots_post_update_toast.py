"""ACE TUI PNG visual snapshot for the post-update toast."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from textual.widgets._toast import Toast

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.tui.actions.post_update_toast import PostUpdateToastMixin
from sase.ace.update_receipt import (
    RepoCommitGroup,
    UpdateToastReceipt,
    UpdateVersionTransition,
    write_pending_update_toast,
)
from sase.dev_update.models import RepoCommit, RepoCommitLog, RepoDiffStat
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _receipt() -> UpdateToastReceipt:
    return UpdateToastReceipt(
        kind="managed",
        created_at=time.time(),
        primary=UpdateVersionTransition("sase", "0.5.0", "0.6.0"),
        plugins=(
            UpdateVersionTransition("sase-github", "1.2.0", "1.3.0"),
            UpdateVersionTransition("sase-telegram", "0.5.0", "0.6.0"),
        ),
        dependency_count=2,
    )


def _diffstat_receipt() -> UpdateToastReceipt:
    return UpdateToastReceipt(
        kind="dev",
        created_at=time.time(),
        primary=UpdateVersionTransition(
            "sase",
            "0.5.0+1.gabc123def",
            "0.5.0+2.gdef456abc",
            diffstat=RepoDiffStat(files_changed=18, insertions=1234, deletions=567),
        ),
        plugins=(
            UpdateVersionTransition(
                "sase-github",
                "1.2.0",
                "1.3.0",
                diffstat=RepoDiffStat(files_changed=4, insertions=42, deletions=7),
            ),
            UpdateVersionTransition(
                "sase-telegram",
                "0.5.0",
                "0.6.0",
                diffstat=RepoDiffStat(files_changed=1, insertions=0, deletions=0),
            ),
        ),
        plugin_overflow=2,
        plugin_overflow_diffstat=RepoDiffStat(
            files_changed=5,
            insertions=80,
            deletions=11,
        ),
        dependency_count=2,
        commit_groups=(
            RepoCommitGroup(
                label="sase",
                commits=RepoCommitLog(
                    total=3,
                    commits=(
                        RepoCommit("def456a", "feat: show applied commits by repo"),
                        RepoCommit("abc123d", "fix: preserve provider receipts"),
                    ),
                ),
            ),
            RepoCommitGroup(
                label="sase-core",
                commits=RepoCommitLog(
                    total=1,
                    commits=(RepoCommit("987fedc", "perf: streamline git parsing"),),
                ),
            ),
        ),
        commit_group_overflow=1,
    )


def _toast_is_mounted(page: AcePage) -> bool:
    return bool(list(page.app.screen.query(Toast)))


async def test_post_update_toast_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The post-update toast confirms the new version without crowding ACE."""
    patch_startup_loaders(monkeypatch)
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    assert write_pending_update_toast(_receipt()) is True
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(post_update_toast=True),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.post_update_toast._TOAST_TIMEOUT_SECONDS",
        300.0,
    )
    maybe_show_toast = PostUpdateToastMixin._maybe_show_post_update_toast
    monkeypatch.setattr(
        PostUpdateToastMixin,
        "_maybe_show_post_update_toast",
        lambda _self: None,
    )

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        notifications=True,
    ) as page:
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        maybe_show_toast(page.app)
        await page.wait_for(lambda _s: bool(list(page.app._notifications)))
        await page.wait_for(lambda _s: _toast_is_mounted(page))
        page.app.screen.set_focus(None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "post_update_toast_120x40",
            title="ACE post-update toast",
        )


async def test_post_update_toast_diffstat_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The dev post-update toast shows churn and applied commits by repo."""
    patch_startup_loaders(monkeypatch)
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    assert write_pending_update_toast(_diffstat_receipt()) is True
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(post_update_toast=True),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.post_update_toast._TOAST_TIMEOUT_SECONDS",
        300.0,
    )
    maybe_show_toast = PostUpdateToastMixin._maybe_show_post_update_toast
    monkeypatch.setattr(
        PostUpdateToastMixin,
        "_maybe_show_post_update_toast",
        lambda _self: None,
    )

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        notifications=True,
    ) as page:
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        maybe_show_toast(page.app)
        await page.wait_for(lambda _s: bool(list(page.app._notifications)))
        await page.wait_for(lambda _s: _toast_is_mounted(page))
        page.app.screen.set_focus(None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "post_update_toast_diffstat_120x40",
            title="ACE post-update toast with line stats",
        )
