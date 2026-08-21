"""Interaction coverage for the Statistics pane."""

from __future__ import annotations

import threading

import pytest
from textual.widgets import Input, Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals import statistics_pane_layout as layout
from sase.ace.tui.modals.statistics_pane_data import (
    STATISTICS_VIEW_BY_ID,
    StatisticsView,
    StatisticsViewData,
    VIEW_ORDER,
)
from sase.ace.tui.modals.statistics_xprompt_picker_modal import (
    StatisticsXPromptPickerModal,
)
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
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
    _assert_statistics_chrome,
    _open_statistics,
    _patch_center,
    _rail_text,
    _rail_widget,
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


@pytest.mark.parametrize(
    ("width", "tier"),
    (
        (130, "full"),
        (120, "compact"),
        (90, "compact"),
        (70, "micro"),
    ),
)
def test_numbered_eight_view_strip_fits_each_statistics_layout_tier(
    width: int,
    tier: str,
) -> None:
    strip = PanelTabStrip(
        layout._VIEW_TABS,
        "overview",
        show_numbers=True,
        uppercase_active=True,
        compact_below=layout._VIEWS_COMPACT_BELOW_WIDTH,
        compact_separator="│",
        micro_below=layout._VIEWS_MICRO_BELOW_WIDTH,
        micro_separator="│",
    )
    strip._tier = tier  # type: ignore[assignment]

    rendered = strip._build_content()

    assert strip._line_width == len(rendered.plain)
    assert strip._line_width <= width
    assert len(strip._tab_ranges) == 8
    assert [
        rendered.plain[start:end].split(maxsplit=1)[0]
        for start, end in strip._tab_ranges.values()
    ] == [f"{number:02d}" for number in range(1, 9)]


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


async def test_view_cycle_reuses_composite_result_and_updates_strip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await page.press("right_square_bracket")
        await page.wait_for(lambda _state: pane._view == "runners")

        assert len(calls) == 1
        _assert_statistics_chrome(pane)

        await page.press("right_square_bracket")
        await page.wait_for(lambda _state: pane._view == "projects")
        assert len(calls) == 1
        _assert_statistics_chrome(pane)

        await page.press("right_square_bracket")
        await page.wait_for(lambda _state: pane._view == "providers")
        await page.press("left_square_bracket")
        await page.wait_for(lambda _state: pane._view == "projects")
        assert len(calls) == 1


async def test_eight_view_keyboard_and_mouse_navigation_share_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        visited = [pane._view]
        for _ in range(len(VIEW_ORDER) - 1):
            await page.press("right_square_bracket")
            visited.append(pane._view)

        assert tuple(visited) == VIEW_ORDER
        await page.wait_for(
            lambda _state: (
                pane._view == "perf"
                and pane._last_result is not None
                and pane._last_result.perf is not None
                and not pane._loading
                and (
                    pane._load_debouncer is None or not pane._load_debouncer.is_pending
                )
            )
        )
        assert len(calls) == 2
        strip = pane.query_one("#statistics-views", PanelTabStrip)
        strip.post_message(PanelTabStrip.TabClicked("runners"))
        await page.wait_for(lambda _state: pane._view == "runners")

        assert VIEW_ORDER[1] == "runners"
        assert VIEW_ORDER[-1] == "perf"
        assert strip._active_tab == "runners"
        assert len(calls) == 2


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


async def test_xprompt_focus_picker_all_clear_key_and_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane.action_focus_xprompt()
        await page.pause()
        assert not isinstance(page.app.screen, StatisticsXPromptPickerModal)

        pane._set_view("xprompts")
        await page.pause()
        xprompt_scope = pane.query_one("#statistics-scope-xprompt", Static)
        assert xprompt_scope.display is True
        assert "x focus" in pane.query_one("#statistics-hints", Static).render().plain

        await page.press("x")
        await page.expect_modal("StatisticsXPromptPickerModal")
        await page.press("down", "enter")
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)

        assert pane._xprompt_focus == "split_file"
        assert calls[-1][3] == "split_file"
        assert "■ #split_file" in _scope_plain(pane, "xprompt")

        await page.press("x")
        await page.expect_modal("StatisticsXPromptPickerModal")
        await page.press("up", "enter")
        await page.wait_for(lambda _state: len(calls) == 3 and not pane._loading)
        assert pane._xprompt_focus is None
        assert calls[-1][3] is None

        await page.press("x")
        await page.expect_modal("StatisticsXPromptPickerModal")
        await page.press("down", "enter")
        await page.wait_for(lambda _state: len(calls) == 4 and not pane._loading)
        await page.press("X")
        await page.wait_for(lambda _state: len(calls) == 5 and not pane._loading)
        assert pane._xprompt_focus is None
        assert calls[-1][3] is None

        await page.press("x")
        await page.expect_modal("StatisticsXPromptPickerModal")
        await page.press("q")
        await page.expect_modal("ConfigCenterModal")
        assert pane._xprompt_focus is None
        assert len(calls) == 5

        pane._set_view("providers")
        await page.pause()
        assert xprompt_scope.display is False


def test_focused_xprompt_body_renders_every_group_and_not_found() -> None:
    pane = sp.StatisticsPane(auto_load=False)
    pane._view = "xprompts"
    pane._xprompt_focus = "split_file"
    result = _result(
        "xprompts",
        pane._range,
        xprompt_focus="split_file",
    )

    expected = {
        "usage": ("Runs over time", "Top models", "Top projects", "Used with"),
        "model": ("By Model", "gpt-5.6"),
        "project": ("By Project", "sase"),
        "pairing": ("Used With", "#gh"),
    }
    for group, phrases in expected.items():
        pane._xprompts_group_by = group  # type: ignore[assignment]
        rendered = _render_plain(pane._xprompts_renderable(result))
        assert "#split_file" in rendered
        assert "Runs  3" in rendered
        assert "Providers" in rendered
        assert "Tribes" in rendered
        assert "Press X to return to All xprompts." in rendered
        for phrase in phrases:
            assert phrase in rendered

    pane._xprompt_focus = "missing"
    missing = _result(
        "xprompts",
        pane._range,
        xprompt_focus="missing",
    )
    rendered = _render_plain(pane._xprompts_renderable(missing))
    assert "#missing has no runs in" in rendered
    assert "Press t to choose another range, or X to return to All xprompts." in (
        rendered
    )


async def test_every_view_selection_path_keeps_heading_tab_rail_and_view_aligned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        assert pane._view == "overview"
        _assert_statistics_chrome(pane)

        await page.press("right_square_bracket")
        await page.wait_for(lambda _state: pane._view == "runners")
        _assert_statistics_chrome(pane)
        assert len(calls) == 1

        await page.press("0", "4")
        await page.wait_for(lambda _state: pane._view == "providers")
        _assert_statistics_chrome(pane)
        assert len(calls) == 1

        strip = pane.query_one("#statistics-views", PanelTabStrip)
        strip.post_message(PanelTabStrip.TabClicked("activity"))
        await page.wait_for(lambda _state: pane._view == "activity")
        _assert_statistics_chrome(pane)
        assert len(calls) == 1

        pane._set_view("overview")
        await page.pause()
        await page.click("#statistics-tile-0")
        await page.wait_for(lambda _state: pane._view == "projects")
        _assert_statistics_chrome(pane)
        assert len(calls) == 1


async def test_pending_perf_load_cannot_restore_stale_rail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    perf_started = threading.Event()
    perf_release = threading.Event()
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    def load(
        view: StatisticsView,
        selected_range: StatsRange,
        project_filter: str | None = None,
        xprompt_focus: str | None = None,
        perf_group_by: str = "subsystem",
    ) -> StatisticsViewData:
        calls.append((view, selected_range, project_filter, xprompt_focus))
        if view == "perf":
            perf_started.set()
            assert perf_release.wait(timeout=5.0)
        return _result(
            view,
            selected_range,
            project_filter=project_filter,
            xprompt_focus=xprompt_focus,
            perf_group_by=perf_group_by,
        )

    monkeypatch.setattr(sp, "load_statistics_view", load)

    try:
        async with AcePage() as page:
            _, pane = await _open_statistics(page)
            pane._set_view("perf")
            await page.wait_for(lambda _state: perf_started.is_set())
            assert pane._view == "perf"
            _assert_statistics_chrome(pane)
            pane._set_view("projects")
            _assert_statistics_chrome(pane)
            rail_after_leave = _rail_text(pane).plain
            perf_release.set()
            await page.wait_for(
                lambda _state: (
                    pane._view == "projects"
                    and not pane._loading
                    and (
                        pane._load_debouncer is None
                        or not pane._load_debouncer.is_pending
                    )
                )
            )
            assert pane._view == "projects"
            _assert_statistics_chrome(pane)
            assert _rail_text(pane).plain == rail_after_leave
            assert STATISTICS_VIEW_BY_ID["perf"].description not in rail_after_leave
    finally:
        perf_release.set()


async def test_failed_perf_load_keeps_the_active_view_rail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    def load(
        view: StatisticsView,
        selected_range: StatsRange,
        project_filter: str | None = None,
        xprompt_focus: str | None = None,
        perf_group_by: str = "subsystem",
    ) -> StatisticsViewData:
        del perf_group_by
        calls.append((view, selected_range, project_filter, xprompt_focus))
        if view == "perf":
            raise RuntimeError("perf exploded")
        return _result(
            view,
            selected_range,
            project_filter=project_filter,
            xprompt_focus=xprompt_focus,
        )

    monkeypatch.setattr(sp, "load_statistics_view", load)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        pane._set_view("perf")
        await page.wait_for(lambda _state: pane._last_error != "" and not pane._loading)
        assert pane._view == "perf"
        _assert_statistics_chrome(pane)
        pane._set_view("runners")
        _assert_statistics_chrome(pane)
        assert STATISTICS_VIEW_BY_ID["perf"].description not in _rail_text(pane).plain


async def test_refresh_and_hidden_tab_keep_the_active_view_rail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        modal, pane = await _open_statistics(page)
        pane._set_view("xprompts")
        _assert_statistics_chrome(pane)
        before = len(calls)
        pane.action_refresh()
        await page.wait_for(
            lambda _state: len(calls) == before + 1 and not pane._loading
        )
        _assert_statistics_chrome(pane)

        await modal._switch_to("config")
        await page.pause()
        assert pane._view == "xprompts"
        pane._on_refresh_tick()
        await page.pause()
        assert len(calls) == before + 1
        await modal._switch_to("statistics")
        await page.wait_for(lambda _state: modal._active_tab == "statistics")
        assert pane._view == "xprompts"
        _assert_statistics_chrome(pane)


async def test_description_rail_cannot_steal_focus_or_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        rail = _rail_widget(pane)
        assert rail.can_focus is False
        await page.click("#statistics-description")
        await page.pause()
        assert page.app.focused is not rail

        await page.press("c")
        custom_input = pane.query_one("#statistics-custom-range", Input)
        assert custom_input.has_focus
        await page.press("escape")
        await page.pause()
        await page.press("0", "3")
        await page.wait_for(lambda _state: pane._view == "projects")
        _assert_statistics_chrome(pane)
        assert len(calls) == 1


async def test_resize_switches_statistics_caption_without_reloading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)

    async with AcePage(size=(120, 40)) as page:
        _, pane = await _open_statistics(page)
        spec = STATISTICS_VIEW_BY_ID["overview"]
        assert _rail_text(pane).plain == f"› {spec.description}"
        before = list(calls)

        await page._pilot.resize_terminal(90, 30)  # noqa: SLF001
        await page.wait_for(
            lambda _state: _rail_text(pane).plain == f"› {spec.compact_description}"
        )
        assert calls == before
        assert page.app.focused is not _rail_widget(pane)

        await page._pilot.resize_terminal(120, 40)  # noqa: SLF001
        await page.wait_for(
            lambda _state: _rail_text(pane).plain == f"› {spec.description}"
        )
        assert calls == before
        _assert_statistics_chrome(pane)
