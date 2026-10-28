"""ACE PNG visual snapshots for the Admin Center Statistics tab."""

from __future__ import annotations

import pytest
from textual.containers import VerticalScroll
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _open_statistics_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_statistics_empty,
    _patch_statistics_footprint,
    _patch_statistics_loading,
    _patch_statistics_perf_degraded,
    _patch_statistics_populated,
    _patch_statistics_projects_measuring_code,
    _patch_macro_sources,
)
from tests.ace.tui.visual._ace_config_center_statistics_fixtures import _WIDGETS_KEY
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _patch_siblings(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_macro_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, None)


async def test_config_center_statistics_overview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
        assert pane._last_result is not None
        assert pane._last_result.views.empty is False

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_overview_120x40",
            title="ACE SASE Admin Center — Statistics overview",
        )


async def test_config_center_statistics_macros_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_perf_degraded(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("perf")
        await wait_for_visual_idle(page)

        assert pane._last_result is not None
        assert pane._last_result.perf is not None
        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_perf_degraded_120x40",
            title="ACE SASE Admin Center — Statistics performance degraded",
        )


async def test_config_center_statistics_help_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("plans_questions")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_plans_questions_120x40",
            title="ACE SASE Admin Center — Statistics plans and questions",
        )


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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_projects_measuring_code(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
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
    _patch_siblings(monkeypatch)
    _patch_statistics_populated(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("projects")
        await _wait_projects_report(page, pane)
        assert pane._compact_scope is True

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_projects_narrow_90x30",
            title="ACE SASE Admin Center — Statistics projects narrow",
        )


async def test_config_center_statistics_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_empty(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page, wait_for_load=False)
        assert pane._loading is True
        assert pane._last_result is None

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_loading_120x40",
            title="ACE SASE Admin Center — Statistics loading state",
        )


async def test_config_center_statistics_footprint_map_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_footprint(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = "textual-dark"
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("footprint")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
            )
        )
        await page.wait_for(lambda _state: pane._footprint_card is not None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_footprint_map_120x40",
            title="ACE SASE Admin Center — Statistics Footprint map",
        )


async def test_config_center_statistics_footprint_cold_card_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_footprint(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        page.app.theme = "textual-light"
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("footprint")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
            )
        )
        await page.press("g")
        await page.wait_for(
            lambda _state: (
                pane._footprint_lens == "cold"
                and pane._last_result is not None
                and pane._last_result.footprint_lens == "cold"
                and not pane._loading
            )
        )
        pane._footprint_selected_index = 1
        pane._paint_current_view()
        pane._schedule_footprint_card()
        await page.wait_for(
            lambda _state: pane._footprint_card_for == ("feature", "cli:bead.close")
        )
        scroll = pane.query_one("#statistics-body-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)
        scroll.scroll_to(y=max(0, scroll.max_scroll_y - 7), animate=False)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_footprint_cold_card_light_90x30",
            title="ACE SASE Admin Center — Statistics Footprint candidate card",
        )


async def test_config_center_statistics_footprint_finder_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_footprint(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = "textual-dark"
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("footprint")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
            )
        )
        await page.wait_for(lambda _state: pane._footprint_card is not None)
        await page.press("slash")
        await page.expect_modal("StatisticsFootprintFinderModal")
        await page.press(
            "v",
            "i",
            "e",
            "w",
            "colon",
            "s",
            "t",
            "a",
            "t",
            "s",
            "full_stop",
            "f",
            "o",
            "o",
            "t",
            "p",
            "r",
            "i",
            "n",
            "t",
        )
        await page.wait_for(
            lambda _state: (
                page.app.screen.query_one(
                    "#statistics-footprint-finder-list", OptionList
                ).option_count
                == 1
            )
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_footprint_finder_120x40",
            title="ACE SASE Admin Center — Statistics Footprint feature finder",
        )


async def test_config_center_statistics_footprint_area_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_footprint(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        page.app.theme = "textual-light"
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("footprint")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
            )
        )
        pane._footprint_selected_index = 1
        pane.action_open_row()
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint_area == "tui.statistics"
                and not pane._loading
            )
        )
        await page.wait_for(
            lambda _state: (
                pane._footprint_card_for == ("feature", "tui:statistics.cycle_range")
            )
        )
        scroll = pane.query_one("#statistics-body-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)
        scroll.scroll_to(y=max(0, scroll.max_scroll_y - 7), animate=False)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_footprint_area_narrow_light_90x30",
            title="ACE SASE Admin Center — Statistics Footprint area",
        )


async def test_config_center_statistics_footprint_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_footprint(monkeypatch, empty=True)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("footprint")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
            )
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_footprint_empty_120x40",
            title="ACE SASE Admin Center — Statistics Footprint empty",
        )


async def test_config_center_statistics_footprint_all_unknown_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_statistics_footprint(monkeypatch, all_unknown=True)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(90, 30),
    ) as page:
        await wait_for_startup(page)
        page.app.theme = "textual-light"
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_statistics_modal(page)
        pane._set_view("footprint")
        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.footprint is not None
                and not pane._loading
            )
        )
        await page.wait_for(lambda _state: pane._footprint_card is not None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_statistics_footprint_all_unknown_light_90x30",
            title="ACE SASE Admin Center — Statistics Footprint all unknown",
        )
