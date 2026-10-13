"""sase's TUI PNG visual snapshots for the Config Center Projects tab.

The Projects pane is fed a deterministic spread of lifecycle records by
overriding the ``conftest`` autouse stub via ``_patch_project_records`` so the
sub-tab shell, state badges, inventory counts, marks, and detail panel are all
exercised with stable data.
"""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.current_project import CurrentProject
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _build_view,
    _config_layers,
    _config_schema,
    _open_projects_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_project_records,
    _patch_macro_sources,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_styled_text_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _patch_admin_center(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current_project: CurrentProject | None = None,
) -> None:
    """Stub every Admin Center pane so the whole modal renders deterministically."""
    patch_startup_loaders(monkeypatch)
    _patch_macro_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_project_records(monkeypatch, current_project=current_project)


_NARROW_HINTS_SIZE = (80, 40)


async def test_config_center_projects_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default Projects sub-tab with both lifecycle states and inventory counts."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_projects_modal(page)
        await page.wait_for(lambda _s: pane._selected_project_name() == "sase")

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_tab_120x40",
            title="ACE SASE Admin Center — Projects tab (projects + inventory counts)",
        )


async def test_config_center_projects_tab_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy 80x24 chrome: list rows, detail, and hints clip off-screen."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(80, 24)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_projects_modal(page)
        await page.wait_for(lambda _s: pane._selected_project_name() == "sase")

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_tab_80x24",
            title="ACE SASE Admin Center — Projects tab (narrow 80x24 clipped chrome)",
        )


async def test_config_center_projects_tab_narrow_hints_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Width-fitted Projects hints stay on-screen at the smallest useful 80-col height."""
    _patch_admin_center(monkeypatch)

    async with AcePage(
        query='"visual"', patches=patches(), size=_NARROW_HINTS_SIZE
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_projects_modal(page)
        await page.wait_for(lambda _s: pane._selected_project_name() == "sase")
        await wait_for_visual_idle(page)

        hints = pane.query_one("#projects-hints", Static)
        region = hints.region
        terminal_height = _NARROW_HINTS_SIZE[1]
        assert region.height > 0
        assert region.y >= 0
        assert region.y + region.height <= terminal_height
        text = pane._hints_text()
        assert text.startswith("n new")
        assert "? help" in text
        list_region = pane.query_one("#projects-list").region
        assert list_region.height >= 3
        assert list_region.y >= 0
        assert list_region.y + list_region.height <= terminal_height

        assert_page_svg_styled_text_contains(page, "n new")
        assert_page_svg_styled_text_contains(page, "? help")

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_tab_narrow_hints_80x40",
            title="ACE SASE Admin Center — Projects tab (narrow hints)",
        )


async def test_config_center_projects_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The empty state names the Projects-tab add/create key."""
    _patch_admin_center(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: [],
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_projects_modal(page)
        await page.wait_for(lambda _s: not pane._records)

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_empty_120x40",
            title="ACE SASE Admin Center — Projects tab (empty)",
        )


async def test_config_center_projects_marked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two marked projects show the ``[✓]`` markers, count, and marked-set hint."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
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


async def test_config_center_projects_disabled_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled projects are visible by default with gold badges and warnings."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_projects_modal(page)
        await page.wait_for(
            lambda _s: any(
                record.state == "disabled" for record in pane._filtered_records
            )
        )
        for _ in range(len(pane._filtered_records)):
            if pane._selected_project_name() == "old-experiment":
                break
            pane.action_next_option()
        await page.wait_for(
            lambda _s: pane._selected_project_name() == "old-experiment"
        )
        await page.wait_for(
            lambda _s: (
                pane._detail_debouncer is None or not pane._detail_debouncer.is_pending
            )
        )
        pane._update_detail()
        page.app.screen.refresh(layout=True)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_inactive_120x40",
            title="ACE SASE Admin Center — Projects tab (disabled project selected)",
        )


async def test_config_center_projects_detail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A warning-heavy disabled row fills the redesigned detail pane."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_projects_modal(page)
        # ``old-prototype`` carries two warnings; step down to it.
        for _ in range(len(pane._filtered_records)):
            if pane._selected_project_name() == "old-prototype":
                break
            pane.action_next_option()
        await page.wait_for(lambda _s: pane._selected_project_name() == "old-prototype")
        await page.wait_for(
            lambda _s: (
                pane._detail_debouncer is None or not pane._detail_debouncer.is_pending
            )
        )
        pane._update_detail()
        page.app.screen.refresh(layout=True)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_detail_120x40",
            title="ACE SASE Admin Center — Projects tab (warning detail)",
        )


async def test_config_center_projects_current_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The current project shows its CUR marker, accent name, and detail badge."""
    _patch_admin_center(
        monkeypatch,
        current_project=CurrentProject(
            project_key="sase",
            display_name="sase",
            origin="project",
            origin_ref="sase",
            workflow_type="gh",
        ),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_projects_modal(page)
        await page.wait_for(lambda _s: pane._selected_project_name() == "sase")
        await page.wait_for(lambda _s: pane._current_project_loaded)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_current_120x40",
            title="ACE SASE Admin Center — Projects tab (current project selected)",
        )
