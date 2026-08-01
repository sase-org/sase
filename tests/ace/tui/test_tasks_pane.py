"""Tests for in-memory tasks in the Admin Center Tasks tab."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from textual.containers import VerticalScroll
from textual.widgets import OptionList

from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.tasks_pane import TasksPane
from sase.ace.tui.modals.tasks_pane_render import _relative_time
from tests.ace.tui._tasks_pane_helpers import (
    TasksTestApp,
    open_tasks_pane,
    output_plain,
    patch_other_panes,
    queue,
    task,
)

_NOW = datetime(2026, 6, 26, 12, 0, 0)


@pytest.fixture(autouse=True)
def _patch_other_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_other_panes(monkeypatch)


def test_relative_time_formats_short_units() -> None:
    assert _relative_time(_NOW - timedelta(seconds=5), now=_NOW) == "5s ago"
    assert _relative_time(_NOW - timedelta(minutes=3), now=_NOW) == "3m ago"
    assert _relative_time(_NOW - timedelta(hours=2), now=_NOW) == "2h ago"
    assert _relative_time(_NOW - timedelta(days=4), now=_NOW) == "4d ago"
    assert _relative_time(_NOW + timedelta(seconds=1), now=_NOW) == "just now"


async def test_tasks_tab_lists_newest_first_and_renders_selected_output() -> None:
    running = task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="Syncing...\nremote: counting\n",
    )
    success = task(
        "ok",
        label="mail sase-41",
        status="success",
        age_seconds=120,
        output="Mailed PR\n",
    )
    error = task(
        "err",
        label="rebase sase-40",
        status="error",
        age_seconds=240,
        output="trace\n",
        error="merge conflict",
    )

    async with TasksTestApp(queue(error, success, running)).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot)

        option_list = pane.query_one("#tasks-list", OptionList)
        assert option_list.highlighted == 0
        assert option_list.option_count == 3
        assert "sync sase-42" in option_list.get_option_at_index(0).prompt.plain
        assert "mail sase-41" in option_list.get_option_at_index(1).prompt.plain
        assert "rebase sase-40" in option_list.get_option_at_index(2).prompt.plain
        assert "Syncing" in output_plain(pane)


async def test_tasks_tab_navigation_updates_output() -> None:
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

    async with TasksTestApp(queue(success, running)).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot)

        await pilot.press("j")
        await pilot.pause()

        assert pane.query_one("#tasks-list", OptionList).highlighted == 1
        assert "Mailed PR" in output_plain(pane)


async def test_tasks_tab_live_refresh_updates_output_and_rebuilds_status() -> None:
    running = task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="line 1\n",
    )
    task_queue = queue(running)

    async with TasksTestApp(task_queue).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot)

        assert running._live_buffer is not None
        running._live_buffer.write("line 2\n")
        pane._refresh_running_output()
        assert "line 2" in output_plain(pane)

        task_queue.complete("run", success=True, message="done", output="finished\n")
        pane._refresh_running_output()

        option = pane.query_one("#tasks-list", OptionList).get_option_at_index(0)
        assert "✓" in option.prompt.plain
        assert "finished" in output_plain(pane)


async def test_tasks_tab_dismisses_selected_and_all_completed() -> None:
    running = task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="Syncing...\n",
    )
    success = task("ok", label="mail sase-41", status="success", age_seconds=120)
    error = task(
        "err",
        label="rebase sase-40",
        status="error",
        age_seconds=240,
        error="merge conflict",
    )
    task_queue = queue(error, success, running)

    async with TasksTestApp(task_queue).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot)
        await pilot.press("j")
        await pilot.pause()

        pane.action_dismiss_task()
        assert task_queue.get("ok") is None
        assert pane.query_one("#tasks-list", OptionList).option_count == 2

        pane.action_dismiss_all_done()
        assert task_queue.get("err") is None
        assert task_queue.get("run") is running
        assert pane.query_one("#tasks-list", OptionList).option_count == 1


async def test_tasks_tab_kill_confirms_and_calls_app_callback() -> None:
    running = task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="Syncing...\n",
    )

    async with TasksTestApp(queue(running)).run_test() as pilot:
        modal, pane = await open_tasks_pane(pilot)

        await pilot.press("K")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ConfirmActionModal)
        confirm = cast(ConfirmActionModal, pilot.app.screen)
        assert confirm._title == "Kill Task"
        assert "sync sase-42" in confirm._message

        await pilot.press("y")
        await pilot.pause()

        app = cast(TasksTestApp, pilot.app)
        assert pilot.app.screen is modal
        assert app.killed_task_ids == ["run"]
        assert running.status == "error"
        assert "Killed by user" in output_plain(pane)


async def test_tasks_tab_empty_state_and_empty_output_guards() -> None:
    async with TasksTestApp(queue()).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot)

        option_list = pane.query_one("#tasks-list", OptionList)
        assert option_list.option_count == 0
        assert "No background tasks yet." in output_plain(pane)

        pane.action_edit_output()
        pane.action_copy_output()
        assert cast(TasksTestApp, pilot.app).notifications == []


async def test_tasks_tab_edit_output_unlinks_temp_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="Syncing...\nDone.\n",
    )
    edited_paths: list[Path] = []

    def fake_run(
        args: list[str],
        *,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del check
        path = Path(args[-1])
        assert path.read_text(encoding="utf-8") == "Syncing...\nDone.\n"
        edited_paths.append(path)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setenv("EDITOR", "cat")
    monkeypatch.setattr(
        "sase.ace.tui.modals.tasks_pane.subprocess.run",
        fake_run,
    )

    @contextmanager
    def fake_suspend(self: TasksTestApp) -> Iterator[None]:
        del self
        yield

    monkeypatch.setattr(TasksTestApp, "suspend", fake_suspend)

    async with TasksTestApp(queue(running)).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot)

        pane.action_edit_output()

    assert edited_paths
    assert not edited_paths[0].exists()


async def test_tasks_tab_scroll_actions_do_not_move_selection() -> None:
    running = task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="".join(f"line {idx}\n" for idx in range(200)),
    )

    async with TasksTestApp(queue(running)).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot)
        scroll = pane.query_one("#tasks-output-scroll", VerticalScroll)
        option_list = pane.query_one("#tasks-list", OptionList)
        highlighted_before = option_list.highlighted

        await pilot.press("G")
        await pilot.pause()
        assert scroll.max_scroll_y > 0
        assert scroll.scroll_y == scroll.max_scroll_y

        await pilot.press("g")
        await pilot.pause()
        assert scroll.scroll_y == 0
        assert option_list.highlighted == highlighted_before
