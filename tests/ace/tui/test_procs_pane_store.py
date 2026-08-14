"""Tests for persisted tasks in the Admin Center Tasks tab."""

from __future__ import annotations

from typing import cast

import pytest
from textual.widgets import OptionList

from sase.ace.testing import wait_for
from sase.ace.tui.modals import procs_pane as tp
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from tests.ace.tui._procs_pane_helpers import (
    ProcsTestApp,
    open_procs_pane,
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

    async with ProcsTestApp(queue(success, running)).run_test() as pilot:
        first, pane = await open_procs_pane(pilot, session_state=state)
        await pilot.press("j")
        await pilot.pause()

        assert state.procs.task.identity == "ok"
        assert pane.query_one("#procs-list", OptionList).highlighted == 1
        assert "Mailed PR" in output_plain(pane)

        first.action_close()
        await pilot.pause()

        _, reopened = await open_procs_pane(pilot, session_state=state)
        await pilot.pause()

        assert reopened is not pane
        assert reopened.query_one("#procs-list", OptionList).highlighted == 1
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

    async with ProcsTestApp(queue(success, running)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        await pilot.press("j")
        await pilot.pause()

        pane.focus_default()
        await pilot.pause()

        assert pane.query_one("#procs-list", OptionList).highlighted == 1
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

    async with ProcsTestApp(queue(running)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        await pilot.pause()

        labels = [
            pane.query_one("#procs-list", OptionList)
            .get_option_at_index(i)
            .prompt.plain
            for i in range(pane.query_one("#procs-list", OptionList).option_count)
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

    async with ProcsTestApp(queue()).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        await pilot.pause()

        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.option_count == 1
        assert "unattributed" in option_list.get_option_at_index(0).prompt.plain
        assert "—" in option_list.get_option_at_index(0).prompt.plain

        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()

        assert pane._all_sessions is True
        assert "all sessions" in pane._title_text()
        option_list = pane.query_one("#procs-list", OptionList)
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

    async with ProcsTestApp(queue()).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        await pilot.pause()
        await pilot.pause()

        option_list = pane.query_one("#procs-list", OptionList)
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

    async with ProcsTestApp(queue()).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        await pilot.pause()

        pane.action_dismiss_task()
        await pilot.pause()

        app = cast(ProcsTestApp, pilot.app)
        assert any("history_limit" in message for message, _ in app.notifications)
        assert pane.query_one("#procs-list", OptionList).option_count == 1


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

    async with ProcsTestApp(queue()).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        await pilot.pause()

        pane._request_store_reload()
        await wait_for(pilot, lambda: not pane._store_load_pending)

    assert calls[-1]["detail_task_id"] == "fff666"
    assert (calls[-1]["known_mtime"] is not None) is expects_cache


async def test_tasks_session_restores_selected_store_row_across_modal_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A store row is not yet in ``_store_rows`` at ``on_mount``, so the
    resumed selection must survive the asynchronous window before it loads.
    """
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
    patch_store_loader(
        monkeypatch,
        [
            store_task(
                "store-detached-1",
                label="detached epic launch",
                status="running",
                session_id=None,
                kind="detached",
            )
        ],
        output="worker: creating beads\n",
    )
    state = AdminCenterSessionState()

    async with ProcsTestApp(queue(success, running)).run_test() as pilot:
        first, pane = await open_procs_pane(pilot, session_state=state)
        await pilot.pause()
        await pilot.pause()

        option_list = pane.query_one("#procs-list", OptionList)
        target_index = next(
            index
            for index in range(option_list.option_count)
            if option_list.get_option_at_index(index).id == "task__store-detached-1"
        )
        for _ in range(target_index):
            await pilot.press("j")
        await pilot.pause()
        await pilot.pause()

        assert state.procs.task.identity == "store-detached-1"
        assert "worker: creating beads" in output_plain(pane)

        first.action_close()
        await pilot.pause()

        _, reopened = await open_procs_pane(pilot, session_state=state)
        await pilot.pause()
        await pilot.pause()

        assert reopened is not pane
        reopened_list = reopened.query_one("#procs-list", OptionList)
        assert reopened_list.highlighted == target_index
        assert (
            reopened_list.get_option_at_index(target_index).id
            == "task__store-detached-1"
        )
        assert "detached epic launch" in output_plain(reopened)


async def test_tasks_fresh_open_selects_newest_row_after_store_rows_arrive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no prior bookmark, a fresh open must settle on the newest merged
    row rather than whatever happened to be row 0 before the store loaded.

    Store rows carry a durable timestamp unrelated to wall-clock time, so
    this drives the pre-/post-store rebuild pair directly rather than via
    real timing, matching the reproduction's asynchronous-arrival window.
    """
    patch_store_loader(monkeypatch, [])
    older = task("older", label="sync older", status="success", age_seconds=50)
    newer = task("newer", label="sync newer", status="success", age_seconds=5)
    state = AdminCenterSessionState()

    async with ProcsTestApp(queue(older)).run_test() as pilot:
        _, pane = await open_procs_pane(pilot, session_state=state)
        if pane._refresh_timer is not None:
            pane._refresh_timer.stop()

        # By now the real mount + focus_default cycle has already settled
        # on an authoritative selection (the store legitimately finished
        # loading zero rows). Reset to a blank bookmark to simulate a
        # genuinely fresh open before driving the pre-/post-store pair below.
        state.procs.task.record(None, None)

        # Pre-store paint: only ``older`` exists yet, so it lands
        # (provisionally) on row 0 even though there is no real bookmark.
        pane._store_loaded_once = False
        pane._store_load_pending = True
        pane._tasks = [older]
        pane._rebuild_list()
        await pilot.pause()

        assert state.procs.task.identity is None
        assert state.procs.task.provisional is True
        assert state.procs.task.displayed_identity == "older"

        # ``newer`` arrives from the store and becomes the true row 0.
        pane._store_loaded_once = True
        pane._store_load_pending = False
        pane._tasks = [newer, older]
        pane._rebuild_list()
        await pilot.pause()

        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.highlighted == 0
        assert option_list.get_option_at_index(0).id == "task__newer"
        assert state.procs.task.identity == "newer"


async def test_tasks_scope_toggle_preserves_store_row_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting a store row and toggling scope must resume that same row
    once the re-scoped store read lands, even though it shifts index.
    """
    patch_store_loader(
        monkeypatch,
        [
            store_task(
                "store-scope-other",
                label="other session task",
                status="success",
                session_id="session-other",
            ),
            store_task(
                "store-scope-mine",
                label="detached scope task",
                status="running",
                session_id=None,
                kind="detached",
            ),
        ],
    )

    async with ProcsTestApp(queue()).run_test() as pilot:
        _, pane = await open_procs_pane(pilot)
        await pilot.pause()
        await pilot.pause()

        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.option_count == 1
        assert option_list.highlighted == 0
        assert pane._selected_task_identity() == "store-scope-mine"

        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()

        assert pane._all_sessions is True
        option_list = pane.query_one("#procs-list", OptionList)
        assert option_list.option_count == 2
        target_index = next(
            index
            for index in range(option_list.option_count)
            if option_list.get_option_at_index(index).id == "task__store-scope-mine"
        )
        assert option_list.highlighted == target_index
        assert pane._selected_task_identity() == "store-scope-mine"
