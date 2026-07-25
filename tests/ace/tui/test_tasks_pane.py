"""Tests for the Admin Center Tasks tab."""

from __future__ import annotations

import io
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import OptionList, Static

from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import logs_pane as lp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals import tasks_pane as tp
from sase.ace.tui.modals.tasks_pane import TasksPane
from sase.ace.tui.modals.tasks_pane_render import _relative_time
from sase.ace.tui.modals.tasks_store_rows import StoreTasksSnapshot, _store_task_row
from sase.ace.tui.task_queue import TaskInfo, TaskQueue
from sase.tasks import BackgroundTask

_NOW = datetime(2026, 6, 26, 12, 0, 0)


@pytest.fixture(autouse=True)
def _patch_other_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    config_result = cp._LoadResult(view=None, error=None, token=("tasks", 1))
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


class _TasksTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, task_queue: TaskQueue) -> None:
        super().__init__()
        self._task_queue = task_queue
        self.killed_task_ids: list[str] = []
        self.notifications: list[tuple[str, str | None]] = []

    def compose(self) -> ComposeResult:
        yield from ()

    def _kill_background_task(self, task_id: str) -> bool:
        self.killed_task_ids.append(task_id)
        self._task_queue.complete(
            task_id,
            success=False,
            message="Killed by user",
            output="",
            error="Killed by user",
        )
        return True

    def notify(
        self,
        message: str,
        *,
        title: str = "",
        severity: str = "information",
        timeout: float | None = None,
        markup: bool = True,
    ) -> None:
        del title, timeout, markup
        self.notifications.append((message, severity))


def _task(
    task_id: str,
    *,
    label: str,
    status: str,
    age_seconds: int,
    output: str = "",
    error: str | None = None,
    live_output: str | None = None,
) -> TaskInfo:
    started_at = datetime.now() - timedelta(seconds=age_seconds)
    info = TaskInfo(
        task_id=task_id,
        task_type=label.split()[0],
        cl_name="",
        project_file="",
        status=status,
        message=f"{label} complete",
        started_at=started_at,
        display_name=label,
        finished_at=(
            started_at + timedelta(seconds=3) if status != "running" else None
        ),
        output=output,
        error=error,
    )
    if live_output is not None:
        info._live_buffer = io.StringIO(live_output)
    return info


def _queue(*tasks: TaskInfo) -> TaskQueue:
    return TaskQueue(_tasks={task.task_id: task for task in tasks})


async def _open_tasks_pane(
    pilot: Any,
) -> tuple[ConfigCenterModal, TasksPane]:
    modal = ConfigCenterModal(initial_tab="tasks")
    pilot.app.push_screen(modal)
    await pilot.pause()
    pane = modal.query_one("#tasks", TasksPane)
    return modal, pane


def _output_plain(pane: TasksPane) -> str:
    return pane.query_one("#tasks-output-content", Static).render().plain


def test_relative_time_formats_short_units() -> None:
    assert _relative_time(_NOW - timedelta(seconds=5), now=_NOW) == "5s ago"
    assert _relative_time(_NOW - timedelta(minutes=3), now=_NOW) == "3m ago"
    assert _relative_time(_NOW - timedelta(hours=2), now=_NOW) == "2h ago"
    assert _relative_time(_NOW - timedelta(days=4), now=_NOW) == "4d ago"
    assert _relative_time(_NOW + timedelta(seconds=1), now=_NOW) == "just now"


async def test_tasks_tab_lists_newest_first_and_renders_selected_output() -> None:
    running = _task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="Syncing...\nremote: counting\n",
    )
    success = _task(
        "ok",
        label="mail sase-41",
        status="success",
        age_seconds=120,
        output="Mailed PR\n",
    )
    error = _task(
        "err",
        label="rebase sase-40",
        status="error",
        age_seconds=240,
        output="trace\n",
        error="merge conflict",
    )

    async with _TasksTestApp(_queue(error, success, running)).run_test() as pilot:
        _, pane = await _open_tasks_pane(pilot)

        option_list = pane.query_one("#tasks-list", OptionList)
        assert option_list.highlighted == 0
        assert option_list.option_count == 3
        assert "sync sase-42" in option_list.get_option_at_index(0).prompt.plain
        assert "mail sase-41" in option_list.get_option_at_index(1).prompt.plain
        assert "rebase sase-40" in option_list.get_option_at_index(2).prompt.plain
        assert "Syncing" in _output_plain(pane)


async def test_tasks_tab_navigation_updates_output() -> None:
    running = _task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="Syncing...\n",
    )
    success = _task(
        "ok",
        label="mail sase-41",
        status="success",
        age_seconds=120,
        output="Mailed PR\n",
    )

    async with _TasksTestApp(_queue(success, running)).run_test() as pilot:
        _, pane = await _open_tasks_pane(pilot)

        await pilot.press("j")
        await pilot.pause()

        assert pane.query_one("#tasks-list", OptionList).highlighted == 1
        assert "Mailed PR" in _output_plain(pane)


async def test_tasks_tab_live_refresh_updates_output_and_rebuilds_status() -> None:
    running = _task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="line 1\n",
    )
    queue = _queue(running)

    async with _TasksTestApp(queue).run_test() as pilot:
        _, pane = await _open_tasks_pane(pilot)

        assert running._live_buffer is not None
        running._live_buffer.write("line 2\n")
        pane._refresh_running_output()
        assert "line 2" in _output_plain(pane)

        queue.complete("run", success=True, message="done", output="finished\n")
        pane._refresh_running_output()

        option = pane.query_one("#tasks-list", OptionList).get_option_at_index(0)
        assert "✓" in option.prompt.plain
        assert "finished" in _output_plain(pane)


async def test_tasks_tab_dismisses_selected_and_all_completed() -> None:
    running = _task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="Syncing...\n",
    )
    success = _task("ok", label="mail sase-41", status="success", age_seconds=120)
    error = _task(
        "err",
        label="rebase sase-40",
        status="error",
        age_seconds=240,
        error="merge conflict",
    )
    queue = _queue(error, success, running)

    async with _TasksTestApp(queue).run_test() as pilot:
        _, pane = await _open_tasks_pane(pilot)
        await pilot.press("j")
        await pilot.pause()

        pane.action_dismiss_task()
        assert queue.get("ok") is None
        assert pane.query_one("#tasks-list", OptionList).option_count == 2

        pane.action_dismiss_all_done()
        assert queue.get("err") is None
        assert queue.get("run") is running
        assert pane.query_one("#tasks-list", OptionList).option_count == 1


async def test_tasks_tab_kill_confirms_and_calls_app_callback() -> None:
    running = _task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="Syncing...\n",
    )

    async with _TasksTestApp(_queue(running)).run_test() as pilot:
        modal, pane = await _open_tasks_pane(pilot)

        await pilot.press("K")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ConfirmActionModal)
        confirm = cast(ConfirmActionModal, pilot.app.screen)
        assert confirm._title == "Kill Task"
        assert "sync sase-42" in confirm._message

        await pilot.press("y")
        await pilot.pause()

        app = cast(_TasksTestApp, pilot.app)
        assert pilot.app.screen is modal
        assert app.killed_task_ids == ["run"]
        assert running.status == "error"
        assert "Killed by user" in _output_plain(pane)


async def test_tasks_tab_empty_state_and_empty_output_guards() -> None:
    async with _TasksTestApp(_queue()).run_test() as pilot:
        _, pane = await _open_tasks_pane(pilot)

        option_list = pane.query_one("#tasks-list", OptionList)
        assert option_list.option_count == 0
        assert "No background tasks yet." in _output_plain(pane)

        pane.action_edit_output()
        pane.action_copy_output()
        assert cast(_TasksTestApp, pilot.app).notifications == []


async def test_tasks_tab_edit_output_unlinks_temp_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = _task(
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
    def fake_suspend(self: _TasksTestApp) -> Iterator[None]:
        del self
        yield

    monkeypatch.setattr(_TasksTestApp, "suspend", fake_suspend)

    async with _TasksTestApp(_queue(running)).run_test() as pilot:
        _, pane = await _open_tasks_pane(pilot)

        pane.action_edit_output()

    assert edited_paths
    assert not edited_paths[0].exists()


async def test_tasks_tab_scroll_actions_do_not_move_selection() -> None:
    running = _task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="".join(f"line {idx}\n" for idx in range(200)),
    )

    async with _TasksTestApp(_queue(running)).run_test() as pilot:
        _, pane = await _open_tasks_pane(pilot)
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


def _store_task(
    task_id: str,
    *,
    label: str,
    status: str,
    session_id: str | None,
    session_label: str | None = None,
    kind: str = "command",
    message: str = "",
) -> BackgroundTask:
    return BackgroundTask(
        task_id=task_id,
        label=label,
        kind=kind,
        status=status,
        command=["sase", "bead", "work", "plan.md"],
        cwd="/tmp",
        origin="cli",
        created_at="2026-06-26T11:58:00Z",
        started_at="2026-06-26T11:58:00Z",
        finished_at=None
        if status in {"pending", "running"}
        else "2026-06-26T11:59:00Z",
        log_path=f"/tmp/{task_id}.log",
        session_id=session_id,
        session_label=session_label,
        message=message or None,
    )


def _patch_store_loader(
    monkeypatch: pytest.MonkeyPatch,
    tasks: list[BackgroundTask],
    *,
    live_session_ids: frozenset[str] = frozenset(),
    output: str = "",
) -> list[dict[str, Any]]:
    """Serve store rows without touching disk, recording each load request."""
    calls: list[dict[str, Any]] = []

    def _fake_load(
        *,
        session_id: str | None,
        all_sessions: bool,
        known_mtime: float | None = None,
        known_detail_task_id: str | None = None,
        detail_task_id: str | None = None,
    ) -> StoreTasksSnapshot:
        calls.append(
            {
                "session_id": session_id,
                "all_sessions": all_sessions,
                "detail_task_id": detail_task_id,
                "known_mtime": known_mtime,
            }
        )
        rows = [
            _store_task_row(task, live_session_ids=live_session_ids)
            for task in tasks
            if all_sessions or task.session_id in (None, session_id)
        ]
        for row in rows:
            if row.task_id == detail_task_id:
                row.output = output
        return StoreTasksSnapshot(
            rows=rows,
            live_session_ids=live_session_ids,
            mtime=1.0,
            detail_task_id=detail_task_id,
            all_sessions=all_sessions,
        )

    monkeypatch.setattr(tp, "load_store_task_rows", _fake_load)
    monkeypatch.setattr(tp, "current_tui_session_id", lambda: "session-mine")
    return calls


async def test_tasks_tab_merges_store_rows_with_in_memory_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = _task(
        "run",
        label="sync sase-42",
        status="running",
        age_seconds=3,
        live_output="Syncing...\n",
    )
    _patch_store_loader(
        monkeypatch,
        [
            _store_task(
                "aaa111",
                label="Epic launch · auth",
                status="running",
                session_id="session-mine",
            ),
            _store_task(
                "bbb222",
                label="other session task",
                status="success",
                session_id="session-other",
            ),
        ],
    )

    async with _TasksTestApp(_queue(running)).run_test() as pilot:
        _, pane = await _open_tasks_pane(pilot)
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
    _patch_store_loader(
        monkeypatch,
        [
            _store_task(
                "bbb222",
                label="other session task",
                status="success",
                session_id="session-other",
                session_label="ace·sase#7",
            ),
            _store_task(
                "ccc333",
                label="unattributed task",
                status="success",
                session_id=None,
            ),
        ],
        live_session_ids=frozenset({"session-other"}),
    )

    async with _TasksTestApp(_queue()).run_test() as pilot:
        _, pane = await _open_tasks_pane(pilot)
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


async def test_tasks_tab_marks_dead_sessions_and_kills_store_backed_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[str] = []
    monkeypatch.setattr(
        tp,
        "kill_store_task",
        lambda task_id: killed.append(task_id) or None,
    )
    _patch_store_loader(
        monkeypatch,
        [
            _store_task(
                "ddd444",
                label="detached epic launch",
                status="running",
                session_id="session-gone",
                session_label="ace·sase#3",
            )
        ],
        live_session_ids=frozenset(),
        output="worker: creating beads\n",
    )

    async with _TasksTestApp(_queue()).run_test() as pilot:
        _, pane = await _open_tasks_pane(pilot)
        pane._all_sessions = True
        pane._request_store_reload(force=True)
        await pilot.pause()
        await pilot.pause()

        option_list = pane.query_one("#tasks-list", OptionList)
        assert option_list.option_count == 1
        # A session that is no longer live renders with the dagger marker.
        assert "†" in option_list.get_option_at_index(0).prompt.plain

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
    _patch_store_loader(
        monkeypatch,
        [
            _store_task(
                "eee555",
                label="finished detached task",
                status="success",
                session_id=None,
            )
        ],
    )

    async with _TasksTestApp(_queue()).run_test() as pilot:
        _, pane = await _open_tasks_pane(pilot)
        await pilot.pause()

        pane.action_dismiss_task()
        await pilot.pause()

        app = cast(_TasksTestApp, pilot.app)
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
    calls = _patch_store_loader(
        monkeypatch,
        [
            _store_task(
                "fff666",
                label="detached task",
                status=status,
                session_id=None,
            )
        ],
        output="line 1\n",
    )

    async with _TasksTestApp(_queue()).run_test() as pilot:
        _, pane = await _open_tasks_pane(pilot)
        await pilot.pause()

        pane._request_store_reload()
        await pilot.pause()
        await pilot.pause()

    assert calls[-1]["detail_task_id"] == "fff666"
    assert (calls[-1]["known_mtime"] is not None) is expects_cache
