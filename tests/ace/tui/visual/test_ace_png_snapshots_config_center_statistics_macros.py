"""ACE PNG snapshots for Statistics macros, runners, and performance views."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_config_center_statistics_png_snapshot_shared import (
    open_statistics_modal,
    patch_siblings,
    patch_statistics_perf_degraded,
    patch_statistics_populated,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_config_center_statistics_macros_png_snapshot(
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
        pane._set_view("macros")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_macros_120x40",
            title="ACE SASE Admin Center — Statistics Macros usage",
        )


async def test_config_center_statistics_macros_model_png_snapshot(
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
        pane._set_view("macros")
        pane.action_cycle_group()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_macros_model_120x40",
            title="ACE SASE Admin Center — Statistics Macros by model",
        )


async def test_config_center_statistics_macros_focus_png_snapshot(
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
        pane._set_view("macros")
        pane._macro_focus = "split_file"
        pane._selection_changed(reload=True)
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.macro_focus == "split_file"
                and not pane._loading
            )
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_macros_focus_120x40",
            title="ACE SASE Admin Center — Statistics focused Macro",
        )


async def test_config_center_statistics_macros_narrow_png_snapshot(
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
        pane._set_view("macros")
        await wait_for_visual_idle(page)

        assert pane._compact_scope is True
        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_macros_narrow_90x30",
            title="ACE SASE Admin Center — Statistics Macros narrow",
        )


async def test_config_center_statistics_runners_png_snapshot(
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
        pane._set_view("runners")
        await wait_for_visual_idle(page)

        assert pane._last_result is not None
        assert pane._last_result.views.runners.available is True
        assert pane._runners_stacked is False
        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_runners_120x40",
            title="ACE SASE Admin Center — Statistics runners",
        )


async def test_config_center_statistics_runners_narrow_png_snapshot(
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
        pane._set_view("runners")
        await wait_for_visual_idle(page)

        assert pane._runners_stacked is True
        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_runners_90x30",
            title="ACE SASE Admin Center — Statistics runners narrow",
        )


async def test_config_center_statistics_perf_png_snapshot(
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
        pane._set_view("perf")
        await wait_for_visual_idle(page)

        assert pane._last_result is not None
        assert pane._last_result.perf is not None
        assert pane._perf_stacked is False
        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_perf_120x40",
            title="ACE SASE Admin Center — Statistics performance",
        )


async def test_config_center_statistics_perf_narrow_png_snapshot(
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
        pane._set_view("perf")
        await wait_for_visual_idle(page)

        assert pane._perf_stacked is True
        assert pane._compact_scope is True
        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_perf_90x30",
            title="ACE SASE Admin Center — Statistics performance narrow",
        )


async def test_config_center_statistics_perf_degraded_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_siblings(monkeypatch)
    patch_statistics_perf_degraded(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await open_statistics_modal(page)
        pane._set_view("perf")
        await wait_for_visual_idle(page)

        assert pane._last_result is not None
        assert pane._last_result.perf is not None
        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_perf_degraded_120x40",
            title="ACE SASE Admin Center — Statistics performance degraded",
        )
