"""UI setup and assertions shared by Statistics pane tests."""

from __future__ import annotations

from typing import Any

import pytest
from rich.console import Console
from rich.text import Text
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.statistics_pane import StatisticsPane
from sase.ace.tui.modals.statistics_pane_data import (
    STATISTICS_VIEW_BY_ID,
    StatisticsView,
    StatisticsViewData,
    statistics_view_description_text,
)
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from sase.stats.perf_query import PerfGroupBy
from sase.stats.ranges import StatsRange
from tests.ace.tui._statistics_pane_results import result as build_statistics_result
from tests.ace.tui._plugins_browser_pane_helpers import (
    patch_other_config_panes,
    patch_plugin_catalog,
    plugin_catalog,
)
from tests._project_display_case import ProjectDisplayCase


def patch_center(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[Any],
    *,
    project_display_case: ProjectDisplayCase | None = None,
) -> None:
    patch_other_config_panes(monkeypatch)
    patch_plugin_catalog(monkeypatch, catalog=plugin_catalog())

    def load(
        view: StatisticsView,
        selected_range: StatsRange,
        project_filter: str | None = None,
        macro_focus: str | None = None,
        perf_group_by: PerfGroupBy = "subsystem",
        **kwargs: object,
    ) -> StatisticsViewData:
        calls.append((view, selected_range, project_filter, macro_focus))
        facets = kwargs.get("facets")
        return build_statistics_result(
            view,
            selected_range,
            project_filter=project_filter,
            project_display_case=project_display_case,
            macro_focus=macro_focus,
            perf_group_by=perf_group_by,
            facets=facets if isinstance(facets, (set, frozenset)) else None,
            footprint_lens=str(kwargs.get("footprint_lens", "map")),
            footprint_actor=str(kwargs.get("footprint_actor", "you")),
            footprint_area=(
                kwargs.get("footprint_area")
                if isinstance(kwargs.get("footprint_area"), str)
                else None
            ),
        )

    def load_code(
        selected_range: StatsRange,
        project_filter: str | None = None,
        *,
        preset: str | None = None,
    ) -> ProjectStatsView:
        del preset
        result = build_statistics_result(
            "projects",
            selected_range,
            project_filter=project_filter,
            project_display_case=project_display_case,
            facets={"code"},
        )
        assert result.project_stats is not None
        return result.project_stats

    monkeypatch.setattr(sp, "load_statistics_view", load)
    monkeypatch.setattr(sp, "_load_project_code_stats", load_code)


async def wait_statistics_settled(
    page: AcePage,
    pane: StatisticsPane,
    *,
    timeout: float = 30.0,
) -> None:
    """Wait until the pane's last result matches the current selection."""
    await page.wait_for(
        lambda _state: (
            not pane._loading
            and (pane._load_debouncer is None or not pane._load_debouncer.is_pending)
            and pane._last_result is not None
            and pane._last_result.selected_range == pane._range
            and pane._last_result.project_filter == pane._project_filter
            and pane._last_result.macro_focus == pane._macro_focus
            and pane._result_matches_selection(pane._last_result)
            and pane._result_paints_view(pane._last_result, pane._view)
            and (pane._view != "projects" or pane._code_complete)
        ),
        timeout=timeout,
    )


async def open_statistics(
    page: AcePage,
) -> tuple[ConfigCenterModal, StatisticsPane]:
    modal = ConfigCenterModal(initial_tab="statistics")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _state: bool(modal.query("#statistics")))
    pane = modal.query_one("#statistics", StatisticsPane)
    await page.wait_for(lambda _state: not pane._loading and pane._loaded_once)
    return modal, pane


def scope_plain(pane: StatisticsPane, name: str) -> str:
    return pane.query_one(f"#statistics-scope-{name}", Static).render().plain


def rail_widget(pane: StatisticsPane) -> Static:
    return pane.query_one("#statistics-description", Static)


def rail_text(pane: StatisticsPane) -> Text:
    content = rail_widget(pane).content
    assert isinstance(content, Text)
    return content


def assert_statistics_chrome(pane: StatisticsPane) -> None:
    spec = STATISTICS_VIEW_BY_ID[pane._view]
    heading = pane.query_one("#statistics-title", Static).render().plain
    assert heading == f"Statistics · {spec.label}"
    strip = pane.query_one("#statistics-views", PanelTabStrip)
    assert strip._active_tab == pane._view
    rail = rail_widget(pane)
    expected = statistics_view_description_text(spec, width=int(rail.size.width))
    content = rail_text(pane)
    assert content.plain == expected.plain
    assert str(content.style) == str(expected.style)
    assert rail.can_focus is False


def assert_range_scope_matches_selection(pane: StatisticsPane) -> None:
    scope = scope_plain(pane, "range")
    assert "Range" in scope
    assert pane._range.display_label in scope
    assert pane._range.label in scope


def render_plain(renderable: object) -> str:
    console = Console(width=180, color_system=None)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()
