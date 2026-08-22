"""Keyboard and monitor-agent navigation tests for the Procs pane."""

from __future__ import annotations

from typing import cast

import pytest
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import OptionList

from sase.ace.tui.models.agent import Agent, AgentType
from sase.monitor_state import MONITOR_GLYPH, MONITOR_PROC_ORIGIN
from tests.ace.tui._procs_pane_helpers import (
    ProcsTestApp,
    hints_plain,
    open_procs_pane,
    output_plain,
    patch_other_panes,
    queue,
    task,
)


@pytest.fixture(autouse=True)
def _patch_other_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_other_panes(monkeypatch)


def _agent(*, monitor_id: str, presented_agent_name: str) -> Agent:
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


def _option_plain(option_list: OptionList, index: int) -> str:
    option = option_list.get_option_at_index(index)
    assert isinstance(option.prompt, Text)
    return option.prompt.plain


async def test_tasks_tab_apostrophe_enters_jump_mode_with_hints() -> None:
    running = task("run", label="sync sase-42", status="running", age_seconds=3)
    success = task("ok", label="mail sase-41", status="success", age_seconds=120)

    async with ProcsTestApp(queue(success, running)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        option_list = pane.query_one("#procs-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.pause()

        assert pane.jump_mode_active is True
        assert _option_plain(option_list, 0).startswith("[0] ")
        assert _option_plain(option_list, 1).startswith("[1] ")
        assert "JUMP ' first" in pane._hints()


async def test_tasks_tab_jump_hint_selects_task_and_shows_output() -> None:
    running = task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="Syncing...\n",
    )
    success = task(
        "ok",
        label="mail sase-41",
        status="success",
        age_seconds=120,
        output="Mailed PR\n",
    )

    async with ProcsTestApp(queue(success, running)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        option_list = pane.query_one("#procs-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.press("1")
        await pilot.pause()

        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == [0]
        assert option_list.highlighted == 1
        assert "Mailed PR" in output_plain(pane)
        assert not _option_plain(option_list, 1).startswith("[1]")


async def test_tasks_tab_apostrophe_in_jump_mode_returns_to_previous_task() -> None:
    running = task("run", label="sync sase-42", status="running", age_seconds=3)
    success = task("ok", label="mail sase-41", status="success", age_seconds=120)

    async with ProcsTestApp(queue(success, running)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        option_list = pane.query_one("#procs-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.press("1")
        await pilot.pause()
        assert option_list.highlighted == 1

        await pilot.press("apostrophe")
        await pilot.pause()
        assert "JUMP ' back" in pane._hints()

        await pilot.press("apostrophe")
        await pilot.pause()

        assert option_list.highlighted == 0
        assert pane.jump_back_stack == []


async def test_tasks_tab_escape_cancels_jump_mode_without_closing_modal() -> None:
    running = task("run", label="sync sase-42", status="running", age_seconds=3)

    async with ProcsTestApp(queue(running)).run_test() as pilot:
        modal, pane = await open_procs_pane(pilot)
        option_list = pane.query_one("#procs-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.pause()
        assert pane.jump_mode_active is True

        await pilot.press("escape")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert pane.jump_mode_active is False
        assert option_list.highlighted == 0
        assert not _option_plain(option_list, 0).startswith("[0]")
        assert "': jump" in pane._hints()


async def test_tasks_tab_jump_mode_takes_g_and_shift_g_from_the_output_scroller() -> (
    None
):
    # Past the ten digit hints, so ``g`` is a real hint character.  Every task
    # is finished, so nothing auto-follows the output panel and only a
    # swallowed g / G could scroll it.
    tasks = [
        task(
            f"t{index:02d}",
            label=f"mail sase-{index}",
            status="success",
            age_seconds=120 + index,
            output="".join(f"line {line}\n" for line in range(200)),
        )
        for index in range(17)
    ]

    async with ProcsTestApp(queue(*tasks)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        option_list = pane.query_one("#procs-list", OptionList)
        scroll = pane.query_one("#procs-output-scroll", VerticalScroll)

        await pilot.press("apostrophe")
        await pilot.pause()
        assert pane._jump_target_count() == 17
        assert pane.jump_hint_for(16) == "g"

        # ``g`` is a hint here, not the output scroller's top key.
        await pilot.press("g")
        await pilot.pause()
        assert pane.jump_mode_active is False
        assert option_list.highlighted == 16
        assert scroll.scroll_y == 0

        # ``G`` needs 43 rows to become a hint, so here it is an invalid hint
        # that exits jump mode -- but it still has to reach the pane's jump
        # handler rather than scrolling the output to the bottom.
        await pilot.press("apostrophe")
        await pilot.pause()
        assert pane.jump_mode_active is True

        await pilot.press("G")
        await pilot.pause()
        assert scroll.max_scroll_y > 0
        assert pane.jump_mode_active is False
        assert scroll.scroll_y == 0


async def test_tasks_tab_refresh_removing_hinted_task_clears_jump_mode() -> None:
    running = task("run", label="sync sase-42", status="running", age_seconds=3)
    success = task("ok", label="mail sase-41", status="success", age_seconds=120)
    proc_queue = queue(success, running)

    async with ProcsTestApp(proc_queue).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        option_list = pane.query_one("#procs-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.pause()
        assert pane.jump_mode_active is True

        proc_queue.remove("run")
        pane._refresh_running_output()
        await pilot.pause()

        assert pane.jump_mode_active is False
        assert option_list.option_count == 1
        assert not _option_plain(option_list, 0).startswith("[0]")


async def test_tasks_tab_marks_monitor_rows_and_names_their_agent() -> None:
    monitor = task(
        "mon-1",
        label="just check-full",
        status="running",
        age_seconds=3,
        live_output="ruff .... Passed\n",
        origin=MONITOR_PROC_ORIGIN,
        shell_name="acme--mon",
    )
    plain = task("run", label="sync sase-42", status="running", age_seconds=1)
    agents = (_agent(monitor_id="mon-1", presented_agent_name="acme--mon"),)

    async with ProcsTestApp(queue(monitor, plain), agents=agents).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)

        option_list = pane.query_one("#procs-list", OptionList)
        monitor_option = option_list.get_option_at_index(1)
        plain_option = option_list.get_option_at_index(0)
        assert f"{MONITOR_GLYPH} just check-full" in monitor_option.prompt.plain
        assert "acme--mon" in monitor_option.prompt.plain
        assert MONITOR_GLYPH not in plain_option.prompt.plain

        await pilot.press("j")
        await pilot.pause()

        assert f"{MONITOR_GLYPH} just check-full" in output_plain(pane)
        assert "agent  acme--mon" in output_plain(pane)


async def test_tasks_tab_enter_on_monitor_row_dismisses_and_reveals_agent() -> None:
    monitor = task(
        "mon-1",
        label="just check-full",
        status="running",
        age_seconds=3,
        origin=MONITOR_PROC_ORIGIN,
        shell_name="acme--mon",
    )
    agent = _agent(monitor_id="mon-1", presented_agent_name="acme--mon")

    async with ProcsTestApp(queue(monitor), agents=(agent,)).run_test() as pilot:
        modal, pane = await open_procs_pane(pilot)

        await pilot.press("enter")
        await pilot.pause()

        app = cast(ProcsTestApp, pilot.app)
        assert pilot.app.screen is not modal
        assert app.current_tab == "agents"
        assert app.save_tab_position_calls == 1
        assert app.reveal_calls == [(agent.identity, "Monitor agent")]


async def test_tasks_tab_enter_on_monitor_row_without_agent_notifies_once() -> None:
    monitor = task(
        "mon-1",
        label="just check-full",
        status="running",
        age_seconds=3,
        origin=MONITOR_PROC_ORIGIN,
        shell_name="acme--mon",
    )

    async with ProcsTestApp(queue(monitor)).run_test() as pilot:
        modal, pane = await open_procs_pane(pilot)

        await pilot.press("enter")
        await pilot.pause()

        app = cast(ProcsTestApp, pilot.app)
        assert pilot.app.screen is modal
        assert app.reveal_calls == []
        assert app.notifications == [
            ("No agent row for acme--mon on the Agents tab", "warning")
        ]


async def test_tasks_tab_enter_on_plain_row_does_nothing() -> None:
    plain = task("run", label="sync sase-42", status="running", age_seconds=1)

    async with ProcsTestApp(queue(plain)).run_test() as pilot:
        modal, pane = await open_procs_pane(pilot)

        await pilot.press("enter")
        await pilot.pause()

        app = cast(ProcsTestApp, pilot.app)
        assert pilot.app.screen is modal
        assert app.reveal_calls == []
        assert app.notifications == []


async def test_tasks_tab_enter_during_jump_mode_is_consumed_by_jump_mode() -> None:
    monitor = task(
        "mon-1",
        label="just check-full",
        status="running",
        age_seconds=3,
        origin=MONITOR_PROC_ORIGIN,
        shell_name="acme--mon",
    )
    agent = _agent(monitor_id="mon-1", presented_agent_name="acme--mon")

    async with ProcsTestApp(queue(monitor), agents=(agent,)).run_test() as pilot:
        modal, pane = await open_procs_pane(pilot)

        await pilot.press("apostrophe")
        await pilot.pause()
        assert pane.jump_mode_active is True

        await pilot.press("enter")
        await pilot.pause()

        app = cast(ProcsTestApp, pilot.app)
        assert pilot.app.screen is modal
        assert app.reveal_calls == []


async def test_tasks_tab_click_selection_reaches_agent_jump_action() -> None:
    monitor = task(
        "mon-1",
        label="just check-full",
        status="running",
        age_seconds=3,
        origin=MONITOR_PROC_ORIGIN,
        shell_name="acme--mon",
    )
    agent = _agent(monitor_id="mon-1", presented_agent_name="acme--mon")

    async with ProcsTestApp(queue(monitor), agents=(agent,)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        option_list = pane.query_one("#procs-list", OptionList)

        pane.on_option_list_option_selected(
            OptionList.OptionSelected(
                option_list, option_list.get_option_at_index(0), 0
            )
        )
        await pilot.pause()

        app = cast(ProcsTestApp, pilot.app)
        assert app.reveal_calls == [(agent.identity, "Monitor agent")]


async def test_tasks_tab_hints_show_agent_token_only_for_resolvable_monitor_rows() -> (
    None
):
    resolvable = task(
        "mon-1",
        label="just check-full",
        status="running",
        age_seconds=1,
        origin=MONITOR_PROC_ORIGIN,
        shell_name="acme--mon",
    )
    unresolvable = task(
        "mon-2",
        label="pytest -x",
        status="running",
        age_seconds=2,
        origin=MONITOR_PROC_ORIGIN,
        shell_name="hotfix--mon",
    )
    plain = task("run", label="sync sase-42", status="running", age_seconds=3)
    agent = _agent(monitor_id="mon-1", presented_agent_name="acme--mon")

    async with ProcsTestApp(
        queue(resolvable, unresolvable, plain), agents=(agent,)
    ).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.highlighted == 0

        assert "⏎: agent" in pane._hints()
        assert "⏎: agent" in hints_plain(pane)

        await pilot.press("j")
        await pilot.pause()
        assert option_list.highlighted == 1
        assert "⏎: agent" not in pane._hints()
        assert "⏎: agent" not in hints_plain(pane)

        await pilot.press("j")
        await pilot.pause()
        assert option_list.highlighted == 2
        assert "⏎: agent" not in pane._hints()
