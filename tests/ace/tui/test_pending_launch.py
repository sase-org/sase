"""Accepted prompt submissions continue as pending launches without the bar.

Submitting from the prompt bar *accepts* the launch: the bar is removed on the
very next paint, and whatever the launch still has to wait for (today, a
``,x`` relaunch cleanup barrier) happens as a visible, cancellable pending
launch that hands off to the durable ``sase run`` proc. ``,X`` cancels a
launch that has not been submitted, and quitting stashes it.
"""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Any

import pytest

import sase.workspace_provider
from sase.ace.patch import Patch
from sase.ace.testing import wait_for
from sase.ace.tui.actions.agent_workflow import _relaunch_barrier
from sase.ace.tui.actions.agent_workflow._launch_records import (
    LaunchRecordState,
    has_pending_launch_kill,
    latest_live_launch_record,
    push_launch_record,
    release_kill_pending_launch_record,
)
from sase.ace.tui.actions.agent_workflow._pending_launch import (
    PendingLaunchStage,
    cancel_pending_launch,
)
from sase.ace.tui.actions.agent_workflow._types import (
    RelaunchOperation,
    begin_prompt_session,
    current_prompt_session,
)
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.proc_observer import ProcObserver
from sase.ace.tui.widgets import PromptInputBar
from sase.core import agent_launch_facade
from tests.ace.tui._agent_launch_helpers import _FakeApp
from tests.ace.tui._kill_and_edit_last_launch_helpers import _context
from tests.ace.tui.test_bulk_marked_patch_launch import (
    _BulkApp,
    _patch,
    _patch_bulk_dependencies,
)
from tests.ace.tui.test_kill_and_edit_launch_barrier import (
    _barriers,
    _done_agent,
    _home_prompt_context,
    _launch_procs,
    _prompt_bar_ready,
    _RealBarLaunchApp,
    _submit_launch,
    _waiting_notified,
)

PROMPT = "%id:!foo\nDo work edited"


class _PendingLaunchApp(_RealBarLaunchApp):
    """Real bar lifecycle plus a live (unstarted) proc observer and a stash spy."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._proc_observer = ProcObserver(on_snapshot=lambda _snapshot: None)
        self.stash_calls: list[str] = []

    def _schedule_failed_launch_prompt_recovery(self, submitted_prompt: str) -> None:
        self.stash_calls.append(submitted_prompt)


def _pending_rows(app: _PendingLaunchApp) -> list[Any]:
    return list(app._proc_observer._pending.values())


def _pending_launches(app: Any) -> list[Any]:
    return list(getattr(app, "_pending_launches", {}).values())


async def _park_launch(app: _PendingLaunchApp, pilot: Any) -> dict[str, Any]:
    """Kill-and-edit a done agent, then submit its edited prompt behind the barrier.

    Returns the open cleanup proc task; its ``proc_callable`` settles the barrier.
    """
    app._kill_and_edit_agent()
    await wait_for(pilot, lambda: bool(app.tracked_procs))
    await wait_for(pilot, lambda: _prompt_bar_ready(app))
    cleanup_task = app.tracked_procs[-1]
    _submit_launch(app, PROMPT)
    await pilot.pause()
    return cleanup_task


def _app_for(tmp_path: Path) -> _PendingLaunchApp:
    agent = _done_agent(tmp_path, "feature", "20260801200000", "%id:foo\nDo work")
    return _PendingLaunchApp([agent], selected=agent)


# --- Submit releases the bar; the launch continues as a pending launch ------


async def test_submit_behind_barrier_removes_bar_and_shows_pending_row(
    tmp_path: Path,
) -> None:
    app = _app_for(tmp_path)

    async with app.run_test(size=(100, 35)) as pilot:
        cleanup_task = await _park_launch(app, pilot)

        # The bar is gone on the very next paint, nothing was submitted, and
        # the launch is visible as a pending row and a ``PREPARING`` record.
        assert not app.query(PromptInputBar)
        assert app._prompt_context is None
        assert _launch_procs(app) == []
        assert _waiting_notified(app)
        (launch,) = _pending_launches(app)
        assert launch.stage is PendingLaunchStage.WAITING_CLEANUP
        (row,) = _pending_rows(app)
        assert row.display_name.startswith("launch ")
        assert row.status == "pending"
        assert row.message == "waiting for kill/dismiss cleanup"
        assert row.exclusive_scopes == frozenset()
        record = latest_live_launch_record(app)
        assert record is not None
        assert record.state is LaunchRecordState.PREPARING
        assert record.proc_ids == ()
        assert record.prompt == PROMPT

        # Settling the cleanup submits exactly once and hands the row and the
        # record to the durable proc.
        cleanup_task["proc_callable"]()
        await wait_for(pilot, lambda: bool(_launch_procs(app)))

        launched = _launch_procs(app)
        assert len(launched) == 1
        assert launched[0]["request"]["prompt"] == PROMPT
        assert _pending_launches(app) == []
        assert _pending_rows(app) == []
        assert record.state is LaunchRecordState.IN_FLIGHT
        assert record.proc_ids == ("task-1",)
        assert record.submitted_prompts == {"task-1": PROMPT}
        assert _barriers(app) == []


async def test_submit_without_barrier_leaves_no_pending_state() -> None:
    app = _PendingLaunchApp([])

    async with app.run_test(size=(100, 35)) as pilot:
        begin_prompt_session(app, _home_prompt_context())
        _submit_launch(app, "%id:new\nnew")
        await pilot.pause()

        assert len(_launch_procs(app)) == 1
        assert _pending_launches(app) == []
        assert _pending_rows(app) == []
        record = latest_live_launch_record(app)
        assert record is not None
        assert record.state is LaunchRecordState.IN_FLIGHT
        assert record.proc_ids == ("task-0",)


async def test_keep_bar_submit_snapshots_context_and_leaves_bar_session_live() -> None:
    app = _PendingLaunchApp([])

    async with app.run_test(size=(100, 35)):
        session = begin_prompt_session(app, _home_prompt_context())
        _submit_launch(app, "%id:pane\npane", keep_bar=True)

        assert len(_launch_procs(app)) == 1
        assert current_prompt_session(app) is session
        assert app._prompt_context is not None


# --- ,X cancels a launch that has not been submitted ------------------------


async def test_kill_last_launch_cancels_pending_launch_and_keeps_replacement_held(
    tmp_path: Path,
) -> None:
    app = _app_for(tmp_path)

    async with app.run_test(size=(100, 35)) as pilot:
        cleanup_task = await _park_launch(app, pilot)
        operation = _barriers(app)[0].operation
        assert operation is not None

        app._kill_and_edit_last_launch()
        await wait_for(pilot, lambda: _prompt_bar_ready(app))

        # The prompt is back in a bar under the same relaunch operation; the
        # pending launch, its waiter, its row, and its record are gone.
        assert app.query_one(PromptInputBar).all_prompt_texts() == [PROMPT]
        session = current_prompt_session(app)
        assert session is not None
        assert session.relaunch_operation is operation
        assert _pending_launches(app) == []
        assert _pending_rows(app) == []
        assert app._relaunch_cleanup_launch_waiters == []
        assert latest_live_launch_record(app) is None
        assert any("prompt restored" in message for message, _ in app.notifications)

        # The replacement submit is still held behind the open barrier.
        replacement = "%id:!foo\nreplacement"
        _submit_launch(app, replacement)
        assert _launch_procs(app) == []

        cleanup_task["proc_callable"]()
        await wait_for(pilot, lambda: bool(_launch_procs(app)))

        launched = _launch_procs(app)
        assert [task["request"]["prompt"] for task in launched] == [replacement]


async def test_settling_after_cancel_launches_nothing(tmp_path: Path) -> None:
    app = _app_for(tmp_path)

    async with app.run_test(size=(100, 35)) as pilot:
        cleanup_task = await _park_launch(app, pilot)

        app._kill_and_edit_last_launch()
        await wait_for(pilot, lambda: _prompt_bar_ready(app))
        cleanup_task["proc_callable"]()
        await pilot.pause()

        assert _launch_procs(app) == []
        assert _barriers(app) == []


async def test_kill_last_launch_skips_record_without_pending_launch() -> None:
    app = _PendingLaunchApp([])

    async with app.run_test(size=(100, 35)):
        orphan = push_launch_record(
            app,
            proc_ids=(),
            prompt="orphan prompt",
            context=_context("orphan"),
            launch_id="gone",
        )
        assert orphan is not None
        assert orphan.state is LaunchRecordState.PREPARING

        app._kill_and_edit_last_launch()

        assert latest_live_launch_record(app) is None
        assert ("No recent launch to kill and edit", "warning") in app.notifications


async def test_replacement_submit_during_inflight_kill_is_a_parked_pending_launch() -> (
    None
):
    app = _PendingLaunchApp([])

    async with app.run_test(size=(100, 35)) as pilot:
        begin_prompt_session(app, _home_prompt_context())
        _submit_launch(app, "%id:foo\nDo work")
        (original,) = _launch_procs(app)
        assert original["request"]["prompt"] == "%id:foo\nDo work"

        # ``,X`` right after submit restores the prompt and waits for the
        # launch to finish so it can be killed.
        app._kill_and_edit_last_launch()
        await wait_for(pilot, lambda: _prompt_bar_ready(app))
        record = latest_live_launch_record(app)
        assert record is not None
        assert has_pending_launch_kill(app)

        replacement = "%id:!foo\nDo work v2"
        _submit_launch(app, replacement)
        await pilot.pause()

        assert not app.query(PromptInputBar)
        assert len(_launch_procs(app)) == 1
        (launch,) = _pending_launches(app)
        assert launch.stage is PendingLaunchStage.WAITING_LAST_LAUNCH
        (row,) = _pending_rows(app)
        assert row.message == "waiting for the last launch to finish"

        # The pending kill is abandoned (its budget ran out): the parked
        # launch replays once, from its own snapshot.
        release_kill_pending_launch_record(record)
        _relaunch_barrier.release_relaunch_holds_if_idle(
            app, operation=record.relaunch_operation
        )

        assert [task["request"]["prompt"] for task in _launch_procs(app)] == [
            "%id:foo\nDo work",
            replacement,
        ]
        assert _pending_launches(app) == []
        assert _pending_rows(app) == []


# --- Abort paths give the prompt back ---------------------------------------


async def test_rejected_submit_restores_prompt_into_a_bar() -> None:
    app = _PendingLaunchApp([])
    app._submit_launch_proc = lambda **_kwargs: None  # type: ignore[method-assign]

    async with app.run_test(size=(100, 35)) as pilot:
        begin_prompt_session(app, _home_prompt_context())
        _submit_launch(app, "%id:new\nnew")
        await wait_for(pilot, lambda: _prompt_bar_ready(app))

        assert app.query_one(PromptInputBar).all_prompt_texts() == ["%id:new\nnew"]
        assert app.stash_calls == []
        assert _pending_launches(app) == []
        assert _pending_rows(app) == []
        assert latest_live_launch_record(app) is None


async def test_rejected_submit_stashes_prompt_when_a_bar_is_mounted() -> None:
    app = _PendingLaunchApp([])
    app._submit_launch_proc = lambda **_kwargs: None  # type: ignore[method-assign]

    async with app.run_test(size=(100, 35)) as pilot:
        begin_prompt_session(app, _home_prompt_context())
        await app.mount(PromptInputBar(initial_value="typing", id="prompt-input-bar"))
        await wait_for(pilot, lambda: _prompt_bar_ready(app))

        # A keep-bar submit leaves the user's bar in place, so an automatic
        # abort must stash instead of overwriting it.
        _submit_launch(app, "%id:pane\npane", keep_bar=True)

        assert app.stash_calls == ["%id:pane\npane"]
        assert app.query_one(PromptInputBar).all_prompt_texts() == ["typing"]
        assert any(
            "prompt saved to stash" in message and severity == "warning"
            for message, severity in app.notifications
        )


# --- Quit stashes pending launches -------------------------------------------


async def test_quit_flush_stashes_parked_launch_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stashed: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        "sase.history.prompt.record_failed_launch_prompt",
        lambda text, *, project=None: stashed.append((text, project)),
    )
    app = _app_for(tmp_path)

    async with app.run_test(size=(100, 35)) as pilot:
        cleanup_task = await _park_launch(app, pilot)

        await app._flush_pending_launch_stashes()

        assert stashed == [(PROMPT, "home")]
        assert _pending_launches(app) == []
        assert _pending_rows(app) == []
        assert latest_live_launch_record(app) is None

        cleanup_task["proc_callable"]()
        await pilot.pause()
        assert _launch_procs(app) == []


async def test_controlled_exit_flushes_pending_launch_stashes_before_quitting() -> None:
    events: list[str] = []

    class _QuitApp(LifecycleMixin):
        async def _flush_pending_launch_stashes(self) -> None:
            events.append("flush")

        def _do_quit(self) -> None:
            events.append("quit")

    await _QuitApp()._flush_then_do_quit()

    assert events == ["flush", "quit"]


# --- Trace ------------------------------------------------------------------


async def test_pending_launch_trace_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "sase.ace.tui.util.trace.trace_event",
        lambda event, **fields: events.append((event, fields)),
    )
    app = _app_for(tmp_path)

    async with app.run_test(size=(100, 35)) as pilot:
        cleanup_task = await _park_launch(app, pilot)
        cleanup_task["proc_callable"]()
        await wait_for(pilot, lambda: bool(_launch_procs(app)))

    accepted = [fields for event, fields in events if event == "launch.accepted"]
    submitted = [fields for event, fields in events if event == "launch.submitted"]
    assert len(accepted) == len(submitted) == 1
    assert accepted[0]["launch_id"] == submitted[0]["launch_id"]
    assert submitted[0]["accept_to_submit_ms"] >= 0
    assert submitted[0]["stages"] == ["waiting_cleanup", "submitting"]


# --- Barrier bookkeeping keyed by launch -------------------------------------


async def test_unrelated_prompt_launches_while_an_older_launch_is_parked() -> None:
    app = _PendingLaunchApp([])
    operation = RelaunchOperation("older kill-and-edit")

    async with app.run_test(size=(100, 35)):
        barrier = _relaunch_barrier.open_relaunch_cleanup_barrier(
            app, "older cleanup", operation=operation
        )
        begin_prompt_session(
            app, _home_prompt_context("older"), relaunch_operation=operation
        )
        _submit_launch(app, "%id:!older\nolder")
        assert _launch_procs(app) == []

        begin_prompt_session(app, _home_prompt_context("unrelated"))
        _submit_launch(app, "%id:unrelated\nunrelated")
        assert [task["request"]["prompt"] for task in _launch_procs(app)] == [
            "%id:unrelated\nunrelated"
        ]

        _relaunch_barrier.settle_relaunch_cleanup_barrier(app, barrier)
        assert [task["request"]["prompt"] for task in _launch_procs(app)] == [
            "%id:unrelated\nunrelated",
            "%id:!older\nolder",
        ]


# --- Bulk fan-out resolves Patches off the UI thread -------------------------


class _ThreadedBulkApp(_BulkApp):
    """Runs workers on a real thread and queues their UI callbacks for the test."""

    def __init__(self) -> None:
        super().__init__()
        self.worker_kwargs: list[dict[str, Any]] = []
        self.ui_queue: list[tuple[Any, tuple[Any, ...]]] = []

    def run_worker(self, work: Any, **kwargs: Any) -> Any:
        self.worker_kwargs.append(kwargs)
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()

    def call_from_thread(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        del kwargs
        self.ui_queue.append((callback, args))

    def drain_ui_queue(self) -> None:
        queued, self.ui_queue = self.ui_queue, []
        for callback, args in queued:
            callback(*args)


def test_bulk_fan_out_resolves_patches_off_the_ui_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_bulk_dependencies(monkeypatch)
    ui_thread = threading.get_ident()
    seen: dict[str, int] = {}
    # ``_patch_bulk_dependencies`` already stubbed all three; wrap those stubs
    # so each records the thread that called it.
    stub_isfile = os.path.isfile
    stub_detect = sase.workspace_provider.detect_workflow_type
    stub_reserve = agent_launch_facade.reserve_launch_timestamp_batch

    def note(name: str) -> None:
        seen.setdefault(name, threading.get_ident())

    def isfile(path: object) -> bool:
        note("isfile")
        return stub_isfile(path)  # type: ignore[arg-type]

    def detect(project_file: str) -> str:
        note("detect")
        return stub_detect(project_file)

    def reserve(count: int) -> list[str]:
        note("reserve")
        return stub_reserve(count)

    monkeypatch.setattr(os.path, "isfile", isfile)
    monkeypatch.setattr("sase.workspace_provider.detect_workflow_type", detect)
    monkeypatch.setattr(
        "sase.core.agent_launch_facade.reserve_launch_timestamp_batch", reserve
    )
    app = _ThreadedBulkApp()
    app._bulk_patches = [
        _patch(name="alpha", file_path="/tmp/proj/alpha.sase"),
        _patch(name="beta", file_path="/tmp/proj/beta.sase"),
    ]

    app._launch_resolved_prompt("shared prompt")

    # The handler only accepted the launch: the marks are consumed and the
    # toast is up, but no Patch was resolved and nothing was submitted.
    assert app._bulk_patches is None
    assert app._artifacts_marked_targets["patches"] == set()
    assert ("Launching 2 agent(s)...", None) in app.notifications
    assert app.launch_tasks == []
    record = latest_live_launch_record(app)
    assert record is not None
    assert record.state is LaunchRecordState.PREPARING
    assert record.context.display_name == "bulk 2 Patches"
    assert app.worker_kwargs[0]["thread"] is True
    assert "exclusive" not in app.worker_kwargs[0]
    assert set(seen) == {"detect", "reserve", "isfile"}
    assert ui_thread not in seen.values()

    # The UI thread only submits the resolved procs and pushes the record.
    app.drain_ui_queue()

    assert [task["cl_name"] for task in app.launch_tasks] == ["alpha", "beta"]
    assert [task["prompt"] for task in app.launch_tasks] == [
        "#gh:alpha shared prompt",
        "#gh:beta shared prompt",
    ]
    assert record.state is LaunchRecordState.IN_FLIGHT
    assert record.proc_ids == ("proc-1", "proc-2")


def test_cancelled_bulk_launch_drops_its_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_bulk_dependencies(monkeypatch)
    app = _ThreadedBulkApp()
    app._bulk_patches = [
        _patch(name="alpha", file_path="/tmp/proj/alpha.sase"),
        _patch(name="beta", file_path="/tmp/proj/beta.sase"),
    ]

    app._launch_resolved_prompt("shared prompt")
    (launch,) = _pending_launches(app)
    cancel_pending_launch(app, launch)
    app.drain_ui_queue()

    assert app.launch_tasks == []
    assert latest_live_launch_record(app) is None


def test_bulk_launch_that_resolves_no_patch_returns_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_bulk_dependencies(monkeypatch)
    stashed: list[str] = []
    app = _BulkApp()
    app._schedule_failed_launch_prompt_recovery = stashed.append  # type: ignore[method-assign]
    app._bulk_patches = [
        Patch(
            name="gone",
            description="d",
            parent=None,
            status="WIP",
            file_path="",
            line_number=1,
        )
    ]

    app._launch_resolved_prompt("shared prompt")

    assert app.launch_tasks == []
    assert stashed == ["shared prompt"]
    assert latest_live_launch_record(app) is None
    assert any("prompt saved to stash" in message for message, _ in app.notifications)


# --- Submit-time Space MRU refresh leaves the UI thread -----------------------


async def test_submit_time_vcs_replay_is_recorded_off_the_ui_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ui_thread = threading.get_ident()
    recorded: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "sase.history.vcs_xprompt_mru.record_vcs_xprompt_usage",
        lambda prefix: recorded.append((prefix, threading.get_ident())),
    )
    app = _FakeApp()

    app._launch_resolved_prompt("#gh:cycled do the work")
    assert recorded == []

    await asyncio.gather(*app._launch_vcs_replay_tasks)  # type: ignore[attr-defined]

    assert [prefix for prefix, _ in recorded] == ["#gh:cycled"]
    assert all(thread != ui_thread for _, thread in recorded)
