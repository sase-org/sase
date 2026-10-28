"""ACE PNG snapshots for the Statistics projects view."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from tests.ace.tui.visual._ace_config_center_statistics_png_snapshot_shared import (
    open_statistics_modal,
    patch_siblings,
    patch_statistics_populated,
    patch_statistics_projects_measuring_code,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_WIDGETS_KEY = "gh_acme__widgets"


async def _wait_projects_report(
    page: AcePage,
    pane: StatisticsPane,
    *,
    code_complete: bool = True,
) -> None:
    await page.wait_for(
        lambda _state: (
            pane._view == "projects"
            and pane._last_result is not None
            and pane._last_result.project_stats is not None
            and not pane._loading
            and (pane._code_complete if code_complete else not pane._code_complete)
        )
    )
    if not code_complete:
        await wait_for_svg_contains(page, "measuring code")
    await wait_for_visual_idle(page)


async def test_config_center_statistics_projects_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("projects")
        await _wait_projects_report(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_projects_120x40",
            title="ACE SASE Admin Center — Statistics projects",
        )


async def test_config_center_statistics_projects_single_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._project_filter = _WIDGETS_KEY
        pane._set_view("projects")
        await _wait_projects_report(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_projects_single_120x40",
            title="ACE SASE Admin Center — Statistics projects, one project",
        )


async def test_config_center_statistics_projects_repo_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("projects")
        await _wait_projects_report(page, pane)
        pane.action_cycle_group()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_projects_repo_120x40",
            title="ACE SASE Admin Center — Statistics projects by repo",
        )


async def test_config_center_statistics_projects_model_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("projects")
        await _wait_projects_report(page, pane)
        pane.action_cycle_group()
        pane.action_cycle_group()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_projects_model_120x40",
            title="ACE SASE Admin Center — Statistics projects by model",
        )


async def test_config_center_statistics_projects_patch_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("projects")
        await _wait_projects_report(page, pane)
        pane.action_cycle_group()
        pane.action_cycle_group()
        pane.action_cycle_group()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_projects_patch_120x40",
            title="ACE SASE Admin Center — Statistics projects by patch",
        )


async def test_config_center_statistics_projects_measuring_code_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_projects_measuring_code(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("projects")
        await _wait_projects_report(page, pane, code_complete=False)
        assert pane._code_complete is False

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_projects_measuring_code_120x40",
            title="ACE SASE Admin Center — Statistics projects measuring code",
        )


async def test_config_center_statistics_projects_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_populated(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("projects")
        await _wait_projects_report(page, pane)
        assert pane._compact_scope is True

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_projects_narrow_90x30",
            title="ACE SASE Admin Center — Statistics projects narrow",
        )
