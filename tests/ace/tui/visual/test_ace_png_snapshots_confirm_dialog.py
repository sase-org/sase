"""ACE TUI PNG visual snapshot coverage for shared confirmation dialogs."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import (
    ConfirmActionModal,
    ConfirmDeleteModal,
    ConfirmDismissAllModal,
    ConfirmKillAllModal,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_confirm_dialog_neutral_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")

        page.app.push_screen(
            ConfirmActionModal(
                "Commit & Push",
                "Commit and push your saved changes?",
                subject="xprompts/review.md",
                icon="↑",
                confirm_label="Commit & push",
                cancel_label="Skip",
                default="confirm",
            )
        )
        await page.expect_modal("ConfirmActionModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "confirm_dialog_neutral_120x40",
            title="ACE neutral confirmation dialog",
        )


async def test_confirm_dialog_danger_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")

        page.app.push_screen(ConfirmDeleteModal("visual-project"))
        await page.expect_modal("ConfirmDeleteModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "confirm_dialog_danger_120x40",
            title="ACE danger confirmation dialog",
        )


async def test_confirm_dialog_dismiss_all_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")

        page.app.push_screen(
            ConfirmDismissAllModal(
                "Dismiss: 2 lanes\n  sase @research.0s.cld\n  sase @research.0s.cdx"
            )
        )
        await page.expect_modal("ConfirmDismissAllModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "confirm_dialog_dismiss_all_120x40",
            title="ACE dismiss-all confirmation dialog",
        )


async def test_confirm_dialog_kill_all_escalated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")

        modal = ConfirmKillAllModal(
            "running: visual.worker, visual.indexer\n"
            "completed: visual.lint, visual.docs"
        )
        page.app.push_screen(modal)
        await page.expect_modal("ConfirmKillAllModal")
        await wait_for_visual_idle(page)

        modal.action_confirm()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "confirm_dialog_kill_all_escalated_120x40",
            title="ACE escalated kill-all confirmation dialog",
        )
