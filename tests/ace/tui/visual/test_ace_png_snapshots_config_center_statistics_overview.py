"""ACE PNG snapshots for Statistics overview, help, and secondary views."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_config_center_statistics_png_snapshot_shared import (
    open_statistics_modal,
    patch_siblings,
    patch_statistics_empty,
    patch_statistics_loading,
    patch_statistics_populated,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_config_center_statistics_overview_png_snapshot(
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
        assert pane._last_result is not None
        assert pane._last_result.views.empty is False

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_overview_120x40",
            title="ACE SASE Admin Center — Statistics overview",
        )


async def test_config_center_statistics_help_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await open_statistics_modal(page)
        await page.press("question_mark")
        await page.expect_modal("StatisticsHelpModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_help_120x40",
            title="ACE SASE Admin Center — Statistics help",
        )


async def test_config_center_statistics_narrow_png_snapshot(
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
        assert pane._compact_scope is True

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_narrow_90x30",
            title="ACE SASE Admin Center — Statistics narrow",
        )


async def test_config_center_statistics_providers_png_snapshot(
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
        pane._set_view("providers")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_providers_120x40",
            title="ACE SASE Admin Center — Statistics providers",
        )


async def test_config_center_statistics_activity_png_snapshot(
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
        pane._set_view("activity")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_activity_120x40",
            title="ACE SASE Admin Center — Statistics activity",
        )


async def test_config_center_statistics_plans_questions_png_snapshot(
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
        pane._set_view("plans_questions")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_plans_questions_120x40",
            title="ACE SASE Admin Center — Statistics plans and questions",
        )


async def test_config_center_statistics_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_empty(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        assert pane._last_result is not None
        assert pane._last_result.views.empty is True

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_empty_120x40",
            title="ACE SASE Admin Center — Statistics empty state",
        )


async def test_config_center_statistics_loading_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_loading(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page, wait_for_load=False)
        assert pane._loading is True
        assert pane._last_result is None

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_loading_120x40",
            title="ACE SASE Admin Center — Statistics loading state",
        )
