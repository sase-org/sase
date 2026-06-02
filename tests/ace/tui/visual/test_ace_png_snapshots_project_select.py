"""ACE TUI PNG visual snapshots for the ``@`` project-select pop-up.

Locks in the compact, centered pop-up layout introduced for the custom-agent
picker: icon'd title with a live match count, prominent filter bar, hint line,
color-coded option list, and footer. Projects and ChangeSpecs are injected
deterministically by patching ``list_launchable_projects`` and
``find_all_changespecs`` in the modal module, so no real project state is read.
"""

from __future__ import annotations

import pytest

from sase.ace.changespec import ChangeSpec
from sase.ace.testing import AcePage
from sase.ace.tui.modals.project_select_modal import ProjectSelectModal
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03


def _select_projects() -> list[str]:
    return ["home", "ace-tui", "rust-core", "telegram-bridge"]


def _select_changespecs() -> list[ChangeSpec]:
    return [
        ChangeSpec(
            name="filter_popup",
            description="Beautiful filterable pop-up for the @ picker.",
            parent=None,
            cl=None,
            status="WIP",
            file_path="/tmp/.sase/projects/ace-tui/ace-tui.sase",
            line_number=1,
        ),
        ChangeSpec(
            name="status_badges",
            description="Sibling project status badges.",
            parent=None,
            cl=None,
            status="Ready",
            file_path="/tmp/.sase/projects/ace-tui/ace-tui.sase",
            line_number=2,
        ),
        ChangeSpec(
            name="core_wire",
            description="Rust core wire update.",
            parent=None,
            cl=None,
            status="Mailed",
            file_path="/tmp/.sase/projects/rust-core/rust-core.sase",
            line_number=1,
        ),
    ]


def _patch_select_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_select_modal.list_launchable_projects",
        _select_projects,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_select_modal.find_all_changespecs",
        _select_changespecs,
    )


async def _open_modal(page: AcePage) -> ProjectSelectModal:
    modal = ProjectSelectModal(include_all=True)
    page.app.push_screen(modal)
    await page.expect_modal("ProjectSelectModal")
    await wait_for_visual_idle(page)
    return modal


async def test_project_select_modal_default_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_select_sources(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_modal(page)

        ace_png_visual.assert_page_png(
            page,
            "project_select_modal_default_120x40",
            title="ACE @ project-select pop-up (default)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_project_select_modal_filtered_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_select_sources(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_modal(page)
        # The filter input auto-focuses on mount; type a query that narrows
        # the list to a single match to exercise the live count + highlight.
        await page.press("c", "o", "r", "e")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "project_select_modal_filtered_120x40",
            title="ACE @ project-select pop-up (filtered)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
