"""Xprompt-focus and description-rail coverage for the Statistics pane."""

from __future__ import annotations

import threading

import pytest
from textual.widgets import Input, Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals.statistics_pane_data import (
    STATISTICS_VIEW_BY_ID,
    StatisticsView,
    StatisticsViewData,
)
from sase.ace.tui.modals.statistics_xprompt_picker_modal import (
    StatisticsXPromptPickerModal,
)
from sase.stats.ranges import StatsRange

from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _patch_catalog,
    _patch_other_panes,
)
from tests.ace.tui._statistics_pane_helpers import (
    _assert_statistics_chrome,
    _open_statistics,
    _patch_center,
    _rail_text,
    _rail_widget,
    _render_plain,
    _result,
    _scope_plain,
)


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
