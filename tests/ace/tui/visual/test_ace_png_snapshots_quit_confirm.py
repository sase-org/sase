"""ACE TUI PNG visual snapshot coverage for quit confirmation."""

from __future__ import annotations

from datetime import datetime

import pytest

import sase.ace.tui.modals.quit_confirm_modal as quit_confirm_modal
from sase.ace.testing import AcePage
from sase.ace.tui.modals import QuitConfirmModal
from sase.ace.tui.task_queue import TaskInfo
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


_FROZEN_ELAPSED = {
    "2026-06-23T12:00:00": "12s",
    "2026-06-23T12:00:01": "4s",
    "2026-06-23T12:00:02": "1m",
    "2026-06-23T12:00:03": "1h 4m",
}


def _frozen_elapsed(started_at: datetime) -> str:
    return _FROZEN_ELAPSED.get(started_at.isoformat(), "30s")


def _task(
    task_id: str,
    task_type: str,
    cl_name: str,
    message: str,
    *,
    started_at: str,
    display_name: str | None = None,
) -> TaskInfo:
    return TaskInfo(
        task_id=task_id,
        task_type=task_type,
        cl_name=cl_name,
        project_file="/tmp/visual_project.sase",
        status="running",
        message=message,
        started_at=datetime.fromisoformat(started_at),
        display_name=display_name,
    )


def _tasks() -> list[TaskInfo]:
    return [
        _task(
            "sync-1",
            "sync",
            "visual-auth",
            "Syncing workspace and applying reviewed ChangeSpec updates...",
            started_at="2026-06-23T12:00:00",
            display_name="sync visual-auth",
        ),
        _task(
            "mail-1",
            "mail",
            "visual-billing",
            "Mailing visual-billing to the review branch...",
            started_at="2026-06-23T12:00:01",
            display_name="mail visual-billing",
        ),
        _task(
            "accept-1",
            "accept",
            "proposal-quit-confirm-panel",
            "Accepting proposal-quit-confirm-panel...",
            started_at="2026-06-23T12:00:02",
            display_name="accept proposal-quit-confirm-panel",
        ),
        _task(
            "launch-1",
            "launch",
            "visual-long",
            (
                "Launching a follow-up agent with a deliberately long status "
                "message that should truncate cleanly inside the task card"
            ),
            started_at="2026-06-23T12:00:03",
            display_name=(
                "launch visual-long-label-that-should-truncate-without-overflow"
            ),
        ),
    ]


async def test_quit_confirm_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(quit_confirm_modal, "_format_elapsed", _frozen_elapsed)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")

        page.app.push_screen(QuitConfirmModal(_tasks()))
        await page.expect_modal("QuitConfirmModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "quit_confirm_modal_120x40",
            title="ACE quit confirmation panel",
        )
