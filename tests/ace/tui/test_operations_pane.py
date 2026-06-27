"""Tests for the Admin Center Operations tab."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.events import Click
from textual.widgets import ContentSwitcher

from sase.ace.tui.actions.base import BaseActionsMixin
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import logs_pane as lp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.logs_pane import LogsPane
from sase.ace.tui.modals.operations_pane import (
    OperationsPane,
    _OperationsSubTabStrip,
)
from sase.ace.tui.modals.tasks_pane import TasksPane
from sase.ace.tui.task_queue import TaskQueue


@pytest.fixture(autouse=True)
def _patch_sibling_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    config_result = cp._LoadResult(view=None, error=None, token=("operations", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: config_result)
    plugins_result = pbp._PluginsLoadResult(catalog=None, error="stub", now=0.0)
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: plugins_result)
    monkeypatch.setattr(
        lp,
        "_build_log_pane_load_result",
        lambda _idx: lp._LogPaneLoadResult([], [], 0, 0, Text("stub")),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: {},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [],
    )


class _OperationsTestApp(BaseActionsMixin, App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self._task_queue = TaskQueue()
        self._admin_center_tab = "config"
        self._operations_subtab = "tasks"

    def compose(self) -> ComposeResult:
        yield from ()


async def _open_operations(
    pilot: Any,
    *,
    initial_subtab: str | None = None,
) -> tuple[ConfigCenterModal, OperationsPane]:
    modal = ConfigCenterModal(
        initial_tab="operations",
        initial_operations_subtab=cast(Any, initial_subtab),
    )
    pilot.app.push_screen(modal)
    await pilot.pause()
    pane = modal.query_one("#operations", OperationsPane)
    return modal, pane


def _operations_switcher(pane: OperationsPane) -> ContentSwitcher:
    return pane.query_one("#operations-switcher", ContentSwitcher)


async def test_operations_defaults_to_tasks_subtab() -> None:
    async with _OperationsTestApp().run_test() as pilot:
        modal, pane = await _open_operations(pilot)

        assert modal._active_tab == "operations"
        assert pane._active_subtab == "tasks"
        assert _operations_switcher(pane).current == "tasks"
        assert pilot.app._operations_subtab == "tasks"


async def test_tab_and_shift_tab_switch_operations_subtabs() -> None:
    async with _OperationsTestApp().run_test() as pilot:
        _, pane = await _open_operations(pilot)

        await pilot.press("tab")
        await pilot.pause()
        assert pane._active_subtab == "logs"
        assert _operations_switcher(pane).current == "logs"
        assert pilot.app._operations_subtab == "logs"

        await pilot.press("shift+tab")
        await pilot.pause()
        assert pane._active_subtab == "tasks"
        assert _operations_switcher(pane).current == "tasks"
        assert pilot.app._operations_subtab == "tasks"


async def test_clicking_operations_subtab_switches_to_it() -> None:
    async with _OperationsTestApp().run_test() as pilot:
        _, pane = await _open_operations(pilot)
        strip = pane.query_one("#operations-subtabs", _OperationsSubTabStrip)
        start, end = strip._subtab_ranges["logs"]
        center_pad = max(0, (int(strip.size.width) - strip._line_width) // 2)
        click_x = center_pad + ((start + end) // 2)

        strip.on_click(cast(Click, SimpleNamespace(x=click_x)))
        await pilot.pause()

        assert pane._active_subtab == "logs"
        assert _operations_switcher(pane).current == "logs"


async def test_operations_subtab_memory_persists_across_reopen() -> None:
    async with _OperationsTestApp().run_test() as pilot:
        _, first = await _open_operations(pilot)
        first.action_next_operations_subtab()
        await pilot.pause()
        assert pilot.app._operations_subtab == "logs"

        await pilot.press("escape")
        await pilot.pause()

        _, reopened = await _open_operations(pilot)
        assert reopened._active_subtab == "logs"
        assert _operations_switcher(reopened).current == "logs"


async def test_is_subtab_active_tracks_outer_and_inner_selection() -> None:
    async with _OperationsTestApp().run_test() as pilot:
        modal, pane = await _open_operations(pilot)
        tasks = modal.query_one("#tasks", TasksPane)
        logs = modal.query_one("#logs", LogsPane)

        assert pane.is_subtab_active(tasks)
        assert not pane.is_subtab_active(logs)
        assert tasks._is_active_tab()
        assert not logs._is_active_tab()

        pane.action_next_operations_subtab()
        await pilot.pause()
        assert not pane.is_subtab_active(tasks)
        assert pane.is_subtab_active(logs)
        assert not tasks._is_active_tab()
        assert logs._is_active_tab()

        modal.action_next_center_tab()
        await pilot.pause()
        assert modal._active_tab == "projects"
        assert not pane.is_subtab_active(logs)
        assert not logs._is_active_tab()


async def test_fast_path_actions_land_on_expected_operations_subtab() -> None:
    async with _OperationsTestApp().run_test() as pilot:
        app = cast(_OperationsTestApp, pilot.app)

        app.action_open_log_panel()
        await pilot.pause()
        modal = cast(ConfigCenterModal, app.screen)
        logs_pane = modal.query_one("#operations", OperationsPane)
        assert modal._active_tab == "operations"
        assert logs_pane._active_subtab == "logs"
        assert app._admin_center_tab == "operations"
        assert app._operations_subtab == "logs"

        await pilot.press("escape")
        await pilot.pause()

        app.action_open_tasks_panel()
        await pilot.pause()
        modal = cast(ConfigCenterModal, app.screen)
        tasks_pane = modal.query_one("#operations", OperationsPane)
        assert modal._active_tab == "operations"
        assert tasks_pane._active_subtab == "tasks"
        assert app._admin_center_tab == "operations"
        assert app._operations_subtab == "tasks"
