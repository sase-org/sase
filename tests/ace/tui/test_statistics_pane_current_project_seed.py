"""Current-project seeding of the Statistics pane's project filter."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.current_project_settings import CurrentProjectSettings
from sase.ace.tui.modals import statistics_pane as sp
from sase.ace.tui.modals.statistics_pane_data import StatisticsView
from sase.current_project import CurrentProject
from sase.stats.ranges import StatsRange

from tests.ace.tui._statistics_pane_helpers import _open_statistics, _patch_center


def _current_project(project_key: str) -> CurrentProject:
    return CurrentProject(
        project_key=project_key,
        display_name=project_key,
        origin="project",
        origin_ref=project_key,
        workflow_type="gh",
    )


async def test_seeds_project_filter_from_current_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)
    monkeypatch.setattr(sp, "resolve_current_project", lambda: _current_project("core"))

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await page.wait_for(lambda _state: pane._project_filter == "core")
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)
        assert calls[-1][2] == "core"
        assert pane._project_filter_seeded is True


async def test_seed_disabled_setting_leaves_all_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)
    resolve_calls: list[int] = []

    def fake_resolve() -> CurrentProject | None:
        resolve_calls.append(1)
        return _current_project("core")

    monkeypatch.setattr(sp, "resolve_current_project", fake_resolve)

    async with AcePage() as page:
        page.app._current_project_settings = CurrentProjectSettings(seed_filters=False)
        _, pane = await _open_statistics(page)
        await page.pause()
        assert pane._project_filter is None
        assert resolve_calls == []


async def test_seed_project_not_in_options_leaves_filter_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)
    monkeypatch.setattr(
        sp, "resolve_current_project", lambda: _current_project("ghost")
    )

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await page.wait_for(lambda _state: pane._project_filter_seeded is True)
        await page.pause()
        assert pane._project_filter is None
        assert len(calls) == 1


async def test_cycle_can_escape_a_seeded_project_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[StatisticsView, StatsRange, str | None, str | None]] = []
    _patch_center(monkeypatch, calls)
    monkeypatch.setattr(sp, "resolve_current_project", lambda: _current_project("core"))

    async with AcePage() as page:
        _, pane = await _open_statistics(page)
        await page.wait_for(lambda _state: pane._project_filter == "core")
        await page.wait_for(lambda _state: len(calls) == 2 and not pane._loading)

        pane.action_cycle_project_filter()
        await page.wait_for(lambda _state: len(calls) == 3 and not pane._loading)
        assert pane._project_filter is None

        # The seed guard must stay settled: no late reseed after escaping it.
        await page.pause()
        assert pane._project_filter is None
