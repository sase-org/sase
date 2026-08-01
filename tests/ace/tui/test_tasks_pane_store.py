"""Tests for persisted tasks in the Admin Center Tasks tab."""

from __future__ import annotations

from typing import cast

import pytest
from textual.widgets import OptionList

from sase.ace.tui.modals import tasks_pane as tp
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from tests.ace.tui._tasks_pane_helpers import (
    TasksTestApp,
    open_tasks_pane,
    output_plain,
    patch_other_panes,
    patch_store_loader,
    queue,
    store_task,
    task,
)


@pytest.fixture(autouse=True)
def _patch_other_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_other_panes(monkeypatch)


async def test_tasks_session_restores_selected_task_across_modal_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(monkeypatch, [])
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
    state = AdminCenterSessionState()

    async with TasksTestApp(queue(success, running)).run_test() as pilot:
        first, pane = await open_tasks_pane(pilot, session_state=state)
        await pilot.press("j")
        await pilot.pause()

        assert state.tasks.task.identity == "ok"
        assert pane.query_one("#tasks-list", OptionList).highlighted == 1
        assert "Mailed PR" in output_plain(pane)

        first.action_close()
        await pilot.pause()

        _, reopened = await open_tasks_pane(pilot, session_state=state)
        await pilot.pause()

        assert reopened is not pane
        assert reopened.query_one("#tasks-list", OptionList).highlighted == 1
        assert "Mailed PR" in output_plain(reopened)


async def test_tasks_focus_default_does_not_reset_selection_to_first_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(monkeypatch, [])
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

        pane.focus_default()
        await pilot.pause()

        assert pane.query_one("#tasks-list", OptionList).highlighted == 1
        assert "Mailed PR" in output_plain(pane)


async def test_tasks_tab_merges_store_rows_with_in_memory_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="Syncing...\n",
    )
    patch_store_loader(
        monkeypatch,
        [
            store_task(
                "aaa111",
                label="Epic launch · auth",
                status="running",
                session_id="session-mine",
            ),
            store_task(
                "bbb222",
                label="other session task",
                status="success",
                session_id="session-other",
            ),
        ],
    )

    async with TasksTestApp(queue(running)).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot)
        await pilot.pause()

        labels = [
            pane.query_one("#tasks-list", OptionList)
            .get_option_at_index(i)
            .prompt.plain
            for i in range(pane.query_one("#tasks-list", OptionList).option_count)
        ]
        joined = "\n".join(labels)
        assert "sync sase-42" in joined
        assert "Epic launch · auth" in joined
        # Default scope hides other sessions.
        assert "other session task" not in joined
        assert "this session" in pane._title_text()


async def test_tasks_tab_scope_toggle_reveals_other_sessions_with_chips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(
        monkeypatch,
        [
            store_task(
                "bbb222",
                label="other session task",
                status="success",
                session_id="session-other",
                session_label="ace·sase#7",
            ),
            store_task(
                "ccc333",
                label="unattributed task",
                status="success",
                session_id=None,
            ),
        ],
        live_session_ids=frozenset({"session-other"}),
    )

    async with TasksTestApp(queue()).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot)
        await pilot.pause()

        option_list = pane.query_one("#tasks-list", OptionList)
        assert option_list.option_count == 1
        assert "unattributed" in option_list.get_option_at_index(0).prompt.plain
        assert "—" in option_list.get_option_at_index(0).prompt.plain

        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()

        assert pane._all_sessions is True
        assert "all sessions" in pane._title_text()
        option_list = pane.query_one("#tasks-list", OptionList)
        rendered = "\n".join(
            option_list.get_option_at_index(i).prompt.plain
            for i in range(option_list.option_count)
        )
        assert "other session task" in rendered
        assert "ace·sase#7" in rendered


async def test_tasks_tab_marks_and_kills_global_detached_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[str] = []
    monkeypatch.setattr(
        tp,
        "kill_store_task",
        lambda task_id: killed.append(task_id) or None,
    )
    patch_store_loader(
        monkeypatch,
        [
            store_task(
                "ddd444",
                label="detached epic launch",
                status="running",
                session_id=None,
                kind="detached",
            )
        ],
        live_session_ids=frozenset(),
        output="worker: creating beads\n",
    )

    async with TasksTestApp(queue()).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot)
        await pilot.pause()
        await pilot.pause()

        option_list = pane.query_one("#tasks-list", OptionList)
        assert option_list.option_count == 1
        assert "◆ detached" in option_list.get_option_at_index(0).prompt.plain
        assert "◆ detached" in output_plain(pane)

        await pilot.press("K")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ConfirmActionModal)
        await pilot.press("y")
        await pilot.pause()
        await pilot.pause()

        assert killed == ["ddd444"]


async def test_tasks_tab_store_rows_cannot_be_dismissed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_store_loader(
        monkeypatch,
        [
            store_task(
                "eee555",
                label="finished detached task",
                status="success",
                session_id=None,
            )
        ],
    )

    async with TasksTestApp(queue()).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot)
        await pilot.pause()

        pane.action_dismiss_task()
        await pilot.pause()

        app = cast(TasksTestApp, pilot.app)
        assert any("history_limit" in message for message, _ in app.notifications)
        assert pane.query_one("#tasks-list", OptionList).option_count == 1


@pytest.mark.parametrize(
    ("status", "expects_cache"),
    [("running", False), ("success", True)],
)
async def test_following_a_live_store_row_bypasses_the_mtime_cache(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expects_cache: bool,
) -> None:
    """A detached task appends to its log without touching the store."""
    calls = patch_store_loader(
        monkeypatch,
        [
            store_task(
                "fff666",
                label="detached task",
                status=status,
                session_id=None,
            )
        ],
        output="line 1\n",
    )

    async with TasksTestApp(queue()).run_test() as pilot:
        _, pane = await open_tasks_pane(pilot)
        await pilot.pause()

        pane._request_store_reload()
        await pilot.pause()
        await pilot.pause()

    assert calls[-1]["detail_task_id"] == "fff666"
    assert (calls[-1]["known_mtime"] is not None) is expects_cache
