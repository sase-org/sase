"""ACE TUI PNG visual snapshots for the Project Management modal.

Locks in the full-screen "command center" layout: header band with state-filter
tabs and counts, aligned column header, the projects list, and the detail pane.
Project records are injected deterministically by patching
``list_project_records`` in the modal module, so no real project state is read.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.project_management_modal import ProjectManagementModal
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    project_records,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03


def _patch_project_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: project_records(),
    )


async def _open_modal(page: AcePage) -> ProjectManagementModal:
    modal = ProjectManagementModal()
    page.app.push_screen(modal)
    await page.expect_modal("ProjectManagementModal")
    await wait_for_visual_idle(page)
    return modal


async def test_project_management_modal_wide_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_project_records(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        modal = await _open_modal(page)
        # Default filter shows only active projects; switch to "all" so the
        # snapshot exercises every state badge and warning style at once.
        await page.press("tab")
        await page.press("tab")
        await page.press("tab")
        await wait_for_visual_idle(page)
        assert modal._state_filter == "all"

        ace_png_visual.assert_page_png(
            page,
            "project_management_modal_120x40",
            title="ACE project management modal (wide, all states)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_project_management_modal_marked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_project_records(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        modal = await _open_modal(page)
        await page.press("m")
        await wait_for_visual_idle(page)
        assert modal._marked_projects

        ace_png_visual.assert_page_png(
            page,
            "project_management_modal_marked_120x40",
            title="ACE project management modal (marked row)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_project_management_modal_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_project_records(monkeypatch)

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(60, 30)
    ) as page:
        await wait_for_startup(page)
        await _open_modal(page)

        ace_png_visual.assert_page_png(
            page,
            "project_management_modal_60x30",
            title="ACE project management modal (narrow degrade)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
