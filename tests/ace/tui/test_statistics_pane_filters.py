"""Range, project-filter, and grouping coverage for the Statistics pane."""

from __future__ import annotations

import pytest
from textual.widgets import Input, Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals.statistics_pane_data import (
    StatisticsView,
    StatisticsViewData,
    VIEW_ORDER,
)
from sase.project_display_names import ProjectDisplaySnapshot
from sase.stats.ranges import StatsRange
from sase.stats.views import build_statistics_views

from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _patch_catalog,
    _patch_other_panes,
)
from tests.ace.tui._statistics_pane_helpers import (
    _NOW,
    _activity_payload,
    _assert_range_scope_matches_selection,
    _open_statistics,
    _patch_center,
    _render_plain,
    _result,
    _run_payload,
    _scope_plain,
)
from tests._project_display_case import ProjectDisplayCase


async def test_range_and_project_group_switches_coalesce_to_latest_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane.action_cycle_project_filter()
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)
        assert pane._project_filter == "sase"

        pane._set_view("projects")
        pane.action_cycle_range()
        pane.action_cycle_range_reverse()
        pane.action_cycle_range()
        pane.action_cycle_group()
        await page.wait_for(
            lambda _state: (
                pane._load_debouncer is not None
                and not pane._load_debouncer.is_pending
                and not pane._loading
                and pane._last_result is not None
                and pane._last_result.selected_range == pane._range
            )
        )

        assert len(calls) == 3
        assert calls[-1][0] == "projects"
        assert calls[-1][1].label == pane._range.label
        assert calls[-1][1].display_label == pane._range.display_label
        assert calls[-1][2] == "sase"
        assert pane._preset_key == "30d"
        assert pane._range.display_label == "Last 30 days"
        assert pane._projects_group_by == "patch"
        _assert_range_scope_matches_selection(pane)


async def test_reverse_range_cycles_backward_wraps_and_reenters_from_custom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        await page.press("T")
        assert pane._preset_key == "24h"
        assert pane._range.display_label == "Last 24 hours"
        pane.action_cycle_range_reverse()
        assert pane._preset_key == "today"
        pane.action_cycle_range_reverse()
        assert pane._preset_key == "all"
        pane.action_cycle_range_reverse()
        assert pane._preset_key == "90d"
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)

        await page.press("c")
        custom_input = pane.query_one("#statistics-custom-range", Input)
        custom_input.value = "14d"
        await page.press("enter")
        await page.wait_for(lambda _state: len(calls) == 3 and not pane._loading)
        assert pane._preset_key is None
        assert pane._custom_range_value == "14d"

        await page.press("T")
        await page.wait_for(lambda _state: len(calls) == 4 and not pane._loading)
        assert pane._preset_key == "all"
        assert pane._range.display_label == "All time"
        assert pane._custom_range_value is None

        await page.press("c")
        custom_input.value = "14d"
        await page.press("enter")
        await page.wait_for(lambda _state: len(calls) == 5 and not pane._loading)
        await page.press("t")
        await page.wait_for(lambda _state: len(calls) == 6 and not pane._loading)
        assert pane._preset_key == "today"
        assert pane._range.display_label == "Today"
        assert pane._custom_range_value is None


async def test_group_cycle_is_view_sensitive_and_projects_reuses_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        grouping_views = {"projects", "xprompts", "perf"}
        for view in VIEW_ORDER:
            pane._set_view(view)
            await page.pause()
            group_scope = pane.query_one("#statistics-scope-group", Static)
            assert group_scope.display is (view in grouping_views)
            if view in grouping_views:
                continue
            pane.action_cycle_group()
            await page.pause()
            assert pane._projects_group_by == "project"
            assert pane._perf_group_by == "subsystem"

        await page.wait_for(
            lambda _state: (
                pane._last_result is not None
                and pane._last_result.perf is not None
                and not pane._loading
                and (
                    pane._load_debouncer is None or not pane._load_debouncer.is_pending
                )
            )
        )
        cached_calls = len(calls)

        pane._set_view("projects")
        pane.action_cycle_group()
        await page.pause()

        assert pane._projects_group_by == "patch"
        assert len(calls) == cached_calls
        assert "Projects · By Patch" in _scope_plain(pane, "group")
        assert "group" not in (
            pane.query_one("#statistics-hints", Static).render().plain
        )

        pane._set_view("xprompts")
        pane.action_cycle_group()
        await page.pause()
        assert pane._xprompts_group_by == "model"
        assert len(calls) == cached_calls
        assert "XPrompts · By Model" in _scope_plain(pane, "group")

        pane._set_view("providers")
        pane.action_cycle_group()
        await page.pause()
        assert pane._projects_group_by == "patch"
        assert pane._xprompts_group_by == "model"
        assert pane._perf_group_by == "subsystem"
        assert len(calls) == cached_calls
        assert pane.query_one("#statistics-scope-group", Static).display is False

        pane._set_view("projects")
        await page.pause()
        assert pane.query_one("#statistics-scope-group", Static).display is True
        assert "Projects · By Patch" in _scope_plain(pane, "group")
        assert len(calls) == cached_calls

        pane._set_view("perf")
        await page.wait_for(
            lambda _state: (
                pane._view == "perf"
                and pane._last_result is not None
                and pane._last_result.perf is not None
                and not pane._loading
            )
        )
        perf_calls = len(calls)
        pane.action_cycle_group()
        await page.wait_for(
            lambda _state: len(calls) == perf_calls + 1 and not pane._loading
        )
        assert pane._perf_group_by == "provider"
        assert "Perf · By Provider" in _scope_plain(pane, "group")
        assert pane.query_one("#statistics-scope-group", Static).display is True


async def test_project_filter_cycles_ranked_projects_and_survives_range_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        pane.action_cycle_project_filter()
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)
        assert pane._project_filter == "sase"
        assert calls[-1][2] == "sase"
        assert "sase" in _scope_plain(pane, "project")
        assert "■" in _scope_plain(pane, "project")
        assert "sase" not in (
            pane.query_one("#statistics-title", Static).render().plain
        )

        pane.action_cycle_range()
        await page.wait_for(lambda _state: len(calls) == 3 and not pane._loading)
        assert calls[-1][1].label == pane._range.label
        assert calls[-1][1].display_label == pane._range.display_label
        assert calls[-1][2] == "sase"
        _assert_range_scope_matches_selection(pane)

        pane.action_cycle_project_filter()
        await page.wait_for(lambda _state: len(calls) == 4 and not pane._loading)
        assert pane._project_filter == "core"
        assert calls[-1][2] == "core"

        pane.action_cycle_project_filter()
        await page.wait_for(lambda _state: len(calls) == 5 and not pane._loading)
        assert pane._project_filter is None
        assert calls[-1][2] is None

        pane.action_cycle_project_filter_reverse()
        await page.wait_for(lambda _state: len(calls) == 6 and not pane._loading)
        assert pane._project_filter == "core"
        assert calls[-1][2] == "core"

        pane.action_cycle_project_filter_reverse()
        await page.wait_for(lambda _state: len(calls) == 7 and not pane._loading)
        assert pane._project_filter == "sase"
        assert calls[-1][2] == "sase"

        pane.action_cycle_project_filter_reverse()
        await page.wait_for(lambda _state: len(calls) == 8 and not pane._loading)
        assert pane._project_filter is None
        assert calls[-1][2] is None


@pytest.mark.parametrize(
    ("key", "expected_filter", "expected_label"),
    (("p", "sase", "SASE"), ("P", "core", "Core")),
)
async def test_empty_project_filter_clears_to_all_projects_in_either_direction(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    expected_filter: str,
    expected_label: str,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    snapshot = ProjectDisplaySnapshot({"sase": "SASE", "core": "Core"})

    def load(
        view: StatisticsView,
        selected_range: StatsRange,
        project_filter: str | None = None,
        xprompt_focus: str | None = None,
        perf_group_by: str = "subsystem",
    ) -> StatisticsViewData:
        del perf_group_by
        calls.append((view, selected_range, project_filter, xprompt_focus))
        return _result(
            view,
            selected_range,
            empty=project_filter is not None,
            project_filter=project_filter,
            project_display_snapshot=snapshot,
            xprompt_focus=xprompt_focus,
        )

    monkeypatch.setattr(sp, "load_statistics_view", load)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        assert pane._project_filter_options == ("sase", "core")

        await page.press(key)
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)
        assert pane._project_filter == expected_filter
        assert pane._last_result is not None
        empty_state = _render_plain(pane._empty_state_renderable(pane._last_result))
        assert f"Press p/P to clear the {expected_label} project filter." in empty_state

        await page.press(key)
        await page.wait_for(lambda _state: len(calls) == 3 and not pane._loading)
        assert pane._project_filter is None
        assert calls[-1][2] is None
        assert "All projects" in _scope_plain(pane, "project")


def test_project_filter_cycle_is_inert_without_choices_and_handles_stale_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = sp.StatisticsPane(auto_load=False)
    changes: list[bool] = []
    monkeypatch.setattr(
        pane,
        "_selection_changed",
        lambda *, reload: changes.append(reload),
    )

    pane.action_cycle_project_filter()
    pane.action_cycle_project_filter_reverse()
    assert pane._project_filter is None
    assert changes == []

    pane._project_filter_options = ("sase", "core")
    pane._project_filter = "stale"
    pane.action_cycle_project_filter()
    assert pane._project_filter == "sase"

    pane._project_filter = "stale"
    pane.action_cycle_project_filter_reverse()
    assert pane._project_filter == "core"
    assert changes == [True, True]


async def test_project_filter_label_submits_canonical_key_across_reload_paths(
    monkeypatch: pytest.MonkeyPatch,
    project_display_case: ProjectDisplayCase,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    widgets_key = project_display_case.project_key
    snapshot = project_display_case.snapshot

    def load(
        view: StatisticsView,
        selected_range: StatsRange,
        project_filter: str | None = None,
        xprompt_focus: str | None = None,
        perf_group_by: str = "subsystem",
    ) -> StatisticsViewData:
        del perf_group_by
        calls.append((view, selected_range, project_filter, xprompt_focus))
        payload = _run_payload(selected_range, "tribe")
        payload["workspaces"][0]["project"] = widgets_key
        payload["work"]["projects"][0]["project"] = widgets_key
        payload["work"]["changespecs"][0]["project"] = widgets_key  # legacy wire key
        return StatisticsViewData(
            view=view,
            selected_range=selected_range,
            generated_at=_NOW,
            views=build_statistics_views(
                payload,
                _activity_payload(),
                project_display_snapshot=snapshot,
            ),
            project_filter=project_filter,
            xprompt_focus=xprompt_focus,
            project_display_snapshot=snapshot,
        )

    monkeypatch.setattr(sp, "load_statistics_view", load)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)

        pane.action_cycle_project_filter()
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)
        project_scope = _scope_plain(pane, "project")
        assert pane._project_filter == widgets_key
        assert calls[-1][2] == widgets_key
        assert project_display_case.project_label in project_scope
        assert widgets_key not in project_scope

        pane.action_cycle_range()
        await page.wait_for(lambda _state: len(calls) == 3 and not pane._loading)
        assert calls[-1][2] == widgets_key

        pane.action_refresh()
        await page.wait_for(lambda _state: len(calls) == 4 and not pane._loading)
        assert calls[-1][2] == widgets_key


async def test_custom_range_accepts_valid_input_and_rejects_invalid_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await page.press("c")
        custom_input = pane.query_one("#statistics-custom-range", Input)
        assert custom_input.display is True
        custom_input.value = "14d"
        await page.press("enter")
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)

        assert pane._preset_key is None
        assert pane._custom_range_value == "14d"
        assert custom_input.display is False
        assert pane._range.display_label == "Last 14 days"
        custom_scope = _scope_plain(pane, "range")
        _assert_range_scope_matches_selection(pane)
        assert "Custom · Last 14 days" in custom_scope

        accepted_range = pane._range
        await page.press("c")
        custom_input.value = "not-a-range"
        await page.press("enter")
        await page.pause()

        assert pane._range == accepted_range
        assert len(calls) == 2
        assert custom_input.display is True
        _assert_range_scope_matches_selection(pane)
