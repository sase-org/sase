"""ACE TUI PNG visual snapshots for the Config Center Projects tab.

The Projects pane is fed a deterministic spread of lifecycle records by
overriding the ``conftest`` autouse stub via ``_patch_project_records`` so the
state badges, column alignment, marks, disabled rows, and detail panel are all
exercised with stable data.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _build_view,
    _config_layers,
    _config_schema,
    _open_projects_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_project_records,
    _patch_xprompt_sources,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _patch_admin_center(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub every Admin Center pane so the whole modal renders deterministically."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_project_records(monkeypatch)


async def test_config_center_projects_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default enabled-state list with the first project's detail populated."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_projects_modal(page)
        await page.wait_for(lambda _s: pane._selected_project_name() == "sase")

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_tab_120x40",
            title="ACE SASE Admin Center — Projects tab (enabled list + detail)",
        )


async def test_config_center_projects_marked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two marked projects show the ``[✓]`` markers, count, and marked-set hint."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_projects_modal(page)
        # Mark auto-advances, so two marks claim the first two enabled rows.
        pane.action_toggle_project_mark()
        pane.action_toggle_project_mark()
        await page.wait_for(lambda _s: pane._marked_projects == {"sase", "sase-core"})
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_marked_120x40",
            title="ACE SASE Admin Center — Projects tab (marked set)",
        )


async def test_config_center_projects_inactive_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revealing disabled rows adds the gold badges and warning counts."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_projects_modal(page)
        pane.action_toggle_inactive_projects()
        await page.wait_for(lambda _s: pane._show_inactive_projects)
        await page.wait_for(
            lambda _s: any(
                record.state == "disabled" for record in pane._filtered_records
            )
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_inactive_120x40",
            title="ACE SASE Admin Center — Projects tab (disabled rows visible)",
        )


async def test_config_center_projects_detail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``all`` filter with a warning-heavy row selected fills the detail pane."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_projects_modal(page)
        # Show every state, then highlight the row carrying two warnings.
        pane.action_cycle_state_filter()  # enabled -> sibling
        pane.action_cycle_state_filter()  # sibling -> disabled
        pane.action_cycle_state_filter()  # disabled -> all
        await page.wait_for(lambda _s: pane._state_filter == "all")
        # ``old-prototype`` is the last row; step down to it (cursor does not wrap).
        for _ in range(len(pane._filtered_records)):
            if pane._selected_project_name() == "old-prototype":
                break
            pane.action_next_option()
        await page.wait_for(lambda _s: pane._selected_project_name() == "old-prototype")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_detail_120x40",
            title="ACE SASE Admin Center — Projects tab (all states + detail)",
        )
