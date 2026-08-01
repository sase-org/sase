"""Selection restoration regressions for the Admin Center Tasks pane."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.tui.modals.config_center_session import AdminCenterSessionState

from tests.ace.tui._tasks_pane_helpers import (
    TasksTestApp,
    open_tasks_pane,
    patch_store_loader,
    queue,
    task,
)


async def test_tasks_loading_echo_preserves_requested_store_bookmark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(monkeypatch, [])
    first = task(
        "first",
        label="sync first",
        status="success",
        age_seconds=10,
    )
    second = task(
        "second",
        label="sync second",
        status="success",
        age_seconds=20,
    )
    requested = task(
        "store-wanted",
        label="sync requested",
        status="success",
        age_seconds=30,
    )
    state = AdminCenterSessionState()

    async with TasksTestApp(queue(second, first)).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot, session_state=state)
        if pane._refresh_timer is not None:
            pane._refresh_timer.stop()
        state.tasks.task.record("store-wanted", 1)
        pane._store_loaded_once = False
        pane._store_load_pending = True
        pane._tasks = [first, second]

        pane._rebuild_list()
        await pilot.pause()

        assert state.tasks.task.identity == "store-wanted"
        assert state.tasks.task.displayed_identity == "second"

        pane._store_load_pending = False
        pane._store_loaded_once = True
        pane._tasks = [first, requested, second]
        pane._rebuild_list()
        await pilot.pause()

        assert pane.query_one("#tasks-list", OptionList).highlighted == 1
        assert state.tasks.task.identity == "store-wanted"


async def test_tasks_stale_rebuild_echo_cannot_record_neighbor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(monkeypatch, [])
    alpha = task(
        "alpha",
        label="sync alpha",
        status="success",
        age_seconds=10,
    )
    beta = task(
        "beta",
        label="sync beta",
        status="success",
        age_seconds=20,
    )
    state = AdminCenterSessionState()

    async with TasksTestApp(queue(beta, alpha)).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot, session_state=state)
        if pane._refresh_timer is not None:
            pane._refresh_timer.stop()
        pane._store_loaded_once = True
        pane._store_load_pending = False
        state.tasks.task.record("beta", 1)

        pane._tasks = [alpha, beta]
        pane._rebuild_list()
        pane._tasks = [beta, alpha]
        pane._rebuild_list()
        await pilot.pause()

        option_list = pane.query_one("#tasks-list", OptionList)
        assert option_list.highlighted == 0
        assert option_list.get_option_at_index(0).id == "task__beta"
        assert state.tasks.task.identity == "beta"


async def test_tasks_bookmark_rekeys_when_durable_id_is_minted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(monkeypatch, [])
    task_info = task(
        "local-task",
        label="sync local",
        status="running",
        age_seconds=10,
    )
    state = AdminCenterSessionState()
    state.tasks.task.record("local-task", 0)

    async with TasksTestApp(queue(task_info)).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot, session_state=state)
        if pane._refresh_timer is not None:
            pane._refresh_timer.stop()

        task_info.durable_task_id = "durable-task"
        pane._tasks = pane._merged_tasks()
        pane._rebuild_list()
        await pilot.pause()

        option_list = pane.query_one("#tasks-list", OptionList)
        assert option_list.highlighted == 0
        assert option_list.get_option_at_index(0).id == "task__durable-task"
        assert state.tasks.task.identity == "durable-task"


async def test_tasks_authoritative_identity_miss_uses_nearest_row_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(monkeypatch, [])
    alpha = task(
        "alpha",
        label="sync alpha",
        status="success",
        age_seconds=10,
    )
    beta = task(
        "beta",
        label="sync beta",
        status="success",
        age_seconds=20,
    )
    state = AdminCenterSessionState()
    state.tasks.task.record("beta", 1)

    async with TasksTestApp(queue(beta, alpha)).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot, session_state=state)
        if pane._refresh_timer is not None:
            pane._refresh_timer.stop()
        pane._store_loaded_once = True
        pane._store_load_pending = False
        pane._tasks = [alpha]

        pane._rebuild_list(highlight_index=1, prior_identity="beta")
        await pilot.pause()

        assert pane.query_one("#tasks-list", OptionList).highlighted == 0
        assert state.tasks.task.identity == "alpha"
