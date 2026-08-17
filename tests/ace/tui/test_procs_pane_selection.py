"""Selection restoration regressions for the Admin Center Tasks pane."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.procs_pane_selection import _resolve_monitor_agent_names
from sase.ace.tui.models.agent import Agent, AgentType
from sase.monitor_state import MONITOR_PROC_ORIGIN

from tests.ace.tui._procs_pane_helpers import (
    ProcsTestApp,
    open_procs_pane,
    patch_store_loader,
    queue,
    task,
)


def _agent(*, monitor_id: str, presented_agent_name: str | None) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/repo/proj.sase",
        status="RUNNING",
        start_time=None,
        monitor_id=monitor_id,
    )
    agent.presented_agent_name = presented_agent_name
    return agent


def test_resolve_monitor_agent_names_prefers_the_matched_agent_row() -> None:
    monitor = task(
        "mon-1",
        label="just check-full",
        status="running",
        age_seconds=1,
        origin=MONITOR_PROC_ORIGIN,
        shell_name="acme--mon",
    )
    agents = [_agent(monitor_id="mon-1", presented_agent_name="acme--mon-renamed")]

    names = _resolve_monitor_agent_names([monitor], agents)

    assert names == {"mon-1": "acme--mon-renamed"}


def test_resolve_monitor_agent_names_falls_back_to_shell_name_without_a_match() -> None:
    monitor = task(
        "mon-1",
        label="just check-full",
        status="running",
        age_seconds=1,
        origin=MONITOR_PROC_ORIGIN,
        shell_name="acme--mon",
    )

    names = _resolve_monitor_agent_names([monitor], [])

    assert names == {"mon-1": "acme--mon"}


def test_resolve_monitor_agent_names_omits_rows_with_neither_source() -> None:
    monitor = task(
        "mon-1",
        label="just check-full",
        status="running",
        age_seconds=1,
        origin=MONITOR_PROC_ORIGIN,
    )

    names = _resolve_monitor_agent_names([monitor], [])

    assert names == {}


def test_resolve_monitor_agent_names_ignores_non_monitor_rows_with_a_shell_name() -> (
    None
):
    # A plain ``sase proc run --shell NAME`` row also carries ``shell_name``;
    # only ``origin == MONITOR_PROC_ORIGIN`` rows may show an agent name.
    plain = task(
        "proc-1",
        label="sase proc run",
        status="running",
        age_seconds=1,
        shell_name="acme--mon",
    )

    names = _resolve_monitor_agent_names([plain], [])

    assert names == {}


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

    async with ProcsTestApp(queue(second, first)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot, session_state=state)
        if pane._refresh_timer is not None:
            pane._refresh_timer.stop()
        state.procs.task.record("store-wanted", 1)
        pane._store_loaded_once = False
        pane._store_load_pending = True
        pane._tasks = [first, second]

        pane._rebuild_list()
        await pilot.pause()

        assert state.procs.task.identity == "store-wanted"
        assert state.procs.task.displayed_identity == "second"

        pane._store_load_pending = False
        pane._store_loaded_once = True
        pane._tasks = [first, requested, second]
        pane._rebuild_list()
        await pilot.pause()

        assert pane.query_one("#procs-list", OptionList).highlighted == 1
        assert state.procs.task.identity == "store-wanted"


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

    async with ProcsTestApp(queue(beta, alpha)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot, session_state=state)
        if pane._refresh_timer is not None:
            pane._refresh_timer.stop()
        pane._store_loaded_once = True
        pane._store_load_pending = False
        state.procs.task.record("beta", 1)

        pane._tasks = [alpha, beta]
        pane._rebuild_list()
        pane._tasks = [beta, alpha]
        pane._rebuild_list()
        await pilot.pause()

        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.highlighted == 0
        assert option_list.get_option_at_index(0).id == "task__beta"
        assert state.procs.task.identity == "beta"


async def test_tasks_bookmark_rekeys_when_durable_id_is_minted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(monkeypatch, [])
    proc_info = task(
        "local-task",
        label="sync local",
        status="running",
        age_seconds=10,
    )
    state = AdminCenterSessionState()
    state.procs.task.record("local-task", 0)

    async with ProcsTestApp(queue(proc_info)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot, session_state=state)
        if pane._refresh_timer is not None:
            pane._refresh_timer.stop()

        proc_info.durable_proc_id = "durable-task"
        pane._tasks = pane._merged_tasks()
        pane._rebuild_list()
        await pilot.pause()

        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.highlighted == 0
        assert option_list.get_option_at_index(0).id == "task__durable-task"
        assert state.procs.task.identity == "durable-task"


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
    state.procs.task.record("beta", 1)

    async with ProcsTestApp(queue(beta, alpha)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot, session_state=state)
        if pane._refresh_timer is not None:
            pane._refresh_timer.stop()
        pane._store_loaded_once = True
        pane._store_load_pending = False
        pane._tasks = [alpha]

        pane._rebuild_list(highlight_index=1, prior_identity="beta")
        await pilot.pause()

        assert pane.query_one("#procs-list", OptionList).highlighted == 0
        assert state.procs.task.identity == "alpha"


async def test_tasks_provisional_highlight_echo_cannot_promote_stand_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A highlight message describing the provisional stand-in row must not
    promote it over a pending request, even if it slips past the
    ``ProgrammaticSelectionGuard`` — e.g. a second rebuild's echo arriving
    after the guard has moved on to a newer intended selection.
    """
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
    state = AdminCenterSessionState()

    async with ProcsTestApp(queue(second, first)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot, session_state=state)
        if pane._refresh_timer is not None:
            pane._refresh_timer.stop()
        state.procs.task.record("store-wanted", 1)
        pane._store_loaded_once = False
        pane._store_load_pending = True
        pane._tasks = [first, second]

        pane._rebuild_list()
        await pilot.pause()

        assert state.procs.task.identity == "store-wanted"
        assert state.procs.task.provisional is True
        assert state.procs.task.displayed_identity == "second"
        assert state.procs.task.displayed_row == 1

        # The guard remembers only one intended selection; clear it to
        # simulate an older echo slipping through after a later rebuild.
        pane._selection_guard.clear()
        option_list = pane.query_one("#procs-list", OptionList)
        pane.on_option_list_option_highlighted(
            OptionList.OptionHighlighted(
                option_list, option_list.get_option_at_index(1), 1
            )
        )
        await pilot.pause()

        assert state.procs.task.identity == "store-wanted"
        assert state.procs.task.provisional is True
