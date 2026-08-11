"""ACE TUI PNG visual snapshots for the ``@`` project-select pop-up.

Locks in the compact, centered pop-up layout introduced for the custom-agent
picker: icon'd title with a live match count, prominent filter bar, hint line,
color-coded option list, and footer. Projects and Patches are injected as
one preloaded snapshot, so no real project state is read by the modal.
"""

from __future__ import annotations

import pytest

from sase.ace.patch import Patch
from sase.ace.testing import AcePage
from sase.ace.tui.modals.project_select_modal import (
    _ProjectSelectData,
    ProjectSelectModal,
)
from sase.project_display_names import ProjectDisplayProjection, ProjectDisplaySnapshot
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _select_projects() -> tuple[ProjectDisplayProjection, ...]:
    return tuple(
        ProjectDisplayProjection(name, name)
        for name in ("home", "ace-tui", "rust-core", "telegram-bridge")
    )


def _select_patches() -> list[Patch]:
    return [
        Patch(
            name="filter_popup",
            description="Beautiful filterable pop-up for the @ picker.",
            parent=None,
            cl=None,
            status="WIP",
            file_path="/tmp/.sase/projects/ace-tui/ace-tui.sase",
            line_number=1,
        ),
        Patch(
            name="status_badges",
            description="Sibling project status badges.",
            parent=None,
            cl=None,
            status="Ready",
            file_path="/tmp/.sase/projects/ace-tui/ace-tui.sase",
            line_number=2,
        ),
        Patch(
            name="core_wire",
            description="Rust core wire update.",
            parent=None,
            cl=None,
            status="Mailed",
            file_path="/tmp/.sase/projects/rust-core/rust-core.sase",
            line_number=1,
        ),
    ]


def _select_data() -> _ProjectSelectData:
    projects = _select_projects()
    return _ProjectSelectData(
        projects=projects,
        patches=tuple(_select_patches()),
        project_display_snapshot=ProjectDisplaySnapshot(
            {item.project_key: item.project_label for item in projects}
        ),
    )


async def _open_modal(page: AcePage) -> ProjectSelectModal:
    modal = ProjectSelectModal(_select_data(), include_all=True)
    page.app.push_screen(modal)
    await page.expect_modal("ProjectSelectModal")
    await wait_for_visual_idle(page)
    return modal


async def test_project_select_modal_default_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await _open_modal(page)

        ace_png_visual.assert_page_png(
            page,
            "project_select_modal_default_120x40",
            title="ACE @ project-select pop-up (default)",
        )


async def test_project_select_modal_filtered_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await _open_modal(page)
        # The filter input auto-focuses on mount; type a query that narrows
        # the list to a single match to exercise the live count + highlight.
        await page.press("c", "o", "r", "e")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "project_select_modal_filtered_120x40",
            title="ACE @ project-select pop-up (filtered)",
        )
