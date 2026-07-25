"""ACE PNG visual snapshots for the Admin Center Statistics tab."""

from __future__ import annotations

import pytest
from textual.containers import VerticalScroll

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _open_statistics_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_statistics_empty,
    _patch_statistics_loading,
    _patch_statistics_populated,
    _patch_xprompt_sources,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _patch_siblings(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, None)


async def test_config_center_statistics_overview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        _, pane = await _open_statistics_modal(page)
        assert pane._last_result is not None
        assert pane._last_result.views.empty is False

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_overview_120x40",
            title="ACE SASE Admin Center — Statistics overview",
        )


async def test_config_center_statistics_runtime_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("runtime")
        await page.pause()

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_runtime_120x40",
            title="ACE SASE Admin Center — Statistics runtime",
        )


async def test_config_center_statistics_runs_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("runs")
        await page.pause()
        pane.query_one("#statistics-body-scroll", VerticalScroll).scroll_end(
            animate=False
        )
        await page.pause()

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_runs_120x40",
            title="ACE SASE Admin Center — Statistics runs",
        )


async def test_config_center_statistics_runners_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("runners")
        await page.pause()

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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("runners")
        await page.pause()

        assert pane._runners_stacked is True
        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_runners_90x30",
            title="ACE SASE Admin Center — Statistics runners narrow",
        )


async def test_config_center_statistics_help_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await _open_statistics_modal(page)
        await page.press("question_mark")
        await page.expect_modal("StatisticsHelpModal")

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_help_120x40",
            title="ACE SASE Admin Center — Statistics help",
        )


async def test_config_center_statistics_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        _, pane = await _open_statistics_modal(page)
        assert pane._compact_scope is True

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_narrow_90x30",
            title="ACE SASE Admin Center — Statistics narrow",
        )


async def test_config_center_statistics_projects_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("projects")
        await page.pause()

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_projects_120x40",
            title="ACE SASE Admin Center — Statistics projects",
        )


async def test_config_center_statistics_projects_drilldown_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("projects")
        pane.action_cycle_group()
        pane.action_cycle_group()
        await page.pause()

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_projects_drilldown_120x40",
            title="ACE SASE Admin Center — Statistics projects drill-down",
        )


async def test_config_center_statistics_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_empty(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_loading(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        _, pane = await _open_statistics_modal(page, wait_for_load=False)
        assert pane._loading is True
        assert pane._last_result is None

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_loading_120x40",
            title="ACE SASE Admin Center — Statistics loading state",
        )
