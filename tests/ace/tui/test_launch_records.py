"""Session launch-record stack coverage for last-launch targeting."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow._launch_procs import (
    LaunchProcMixin,
    _LaunchProcOutcome,
)
from sase.ace.tui.actions.agent_workflow._launch_records import (
    LaunchRecordContext,
    LaunchRecordState,
    MAX_SESSION_LAUNCH_RECORDS,
    consume_launch_record,
    has_pending_launch_kill,
    latest_live_launch_record,
    push_launch_record,
    rename_launch_record_proc_id,
    stamp_launch_record_failure,
    stamp_launch_record_results,
)
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.proc_observer import ObservedProc
from sase.agent.launch_types import AgentLaunchResult
from tests.ace.tui._agent_launch_helpers import _FakeApp
from tests.ace.tui.test_bulk_marked_patch_launch import (
    _BulkApp,
    _patch,
    _patch_bulk_dependencies,
)


def _context(display_name: str = "demo") -> LaunchRecordContext:
    return LaunchRecordContext(
        display_name=display_name,
        project_file=f"/tmp/projects/{display_name}/{display_name}.sase",
        cl_name=display_name,
        is_project_agent=True,
    )


def _result(identity: str) -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=100,
        workspace_num=1,
        workspace_dir="/tmp/workspace",
        output_path=f"/tmp/artifacts/{identity}/live_reply.md",
        project_file=f"/tmp/projects/{identity}/{identity}.sase",
        project_name=identity,
        workflow_name=f"ace(run)-{identity}",
        cl_name=identity,
        timestamp="20260903170000",
        artifacts_dir=f"/tmp/artifacts/{identity}",
        agent_name=identity,
    )


def _completion(
    proc_id: str,
    payload: object,
    *,
    success: bool = True,
) -> TrackedProcCompletion[object]:
    return TrackedProcCompletion(
        proc_info=ObservedProc(
            proc_id=proc_id,
            proc_type="launch",
            cl_name="demo",
            project_file="/tmp/projects/demo/demo.sase",
            status="success" if success else "error",
            message="done",
            started_at=datetime.now(),
            display_name="launch demo",
        ),
        success=success,
        message="done",
        output="",
        payload=payload,
        error=None if success else "failed",
    )


class _RejectingSubmitApp(_FakeApp):
    def _submit_launch_proc(self, **kwargs: Any) -> None:
        self.launch_tasks.append(dict(kwargs))
        return None


class _CompletionApp(LaunchProcMixin):
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.delta_states: list[LaunchRecordState] = []

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def _handle_launch_results_delta(self, results: object) -> None:
        del results
        record = latest_live_launch_record(self)
        assert record is not None
        self.delta_states.append(record.state)

    def request_agents_refresh(self, source: str) -> None:
        del source

    def _schedule_agents_async_refresh(self, *, source: str = "launch") -> None:
        del source

    def _schedule_prompt_stash_badge_refresh(self) -> None:
        pass


def test_accepted_submit_pushes_launch_record() -> None:
    app = _FakeApp()

    app._launch_resolved_prompt("plain prompt")

    record = latest_live_launch_record(app)
    assert record is not None
    assert record.proc_ids == ("proc-1",)
    assert record.prompt == "plain prompt"
    assert record.submitted_prompts == {"proc-1": "plain prompt"}
    assert record.context.display_name == "test"
    assert record.state is LaunchRecordState.IN_FLIGHT


def test_rejected_submit_leaves_prior_target_unchanged() -> None:
    app = _RejectingSubmitApp()
    prior = push_launch_record(
        app,
        proc_ids=("prior",),
        prompt="prior prompt",
        context=_context("prior"),
    )

    app._launch_resolved_prompt("rejected prompt")

    assert prior is not None
    assert latest_live_launch_record(app) is prior
    assert app._session_launch_records == [prior]


def test_late_completion_updates_only_own_record() -> None:
    app = SimpleNamespace()
    older = push_launch_record(
        app,
        proc_ids=("older",),
        prompt="older prompt",
        context=_context("older"),
    )
    newer = push_launch_record(
        app,
        proc_ids=("newer",),
        prompt="newer prompt",
        context=_context("newer"),
    )

    stamp_launch_record_results(app, "older", (_result("older"),))

    assert older is not None
    assert newer is not None
    assert older.state is LaunchRecordState.RESOLVED
    assert newer.state is LaunchRecordState.IN_FLIGHT
    assert latest_live_launch_record(app) is newer


def test_bulk_patch_gesture_pushes_one_record_and_resolves_when_all_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_bulk_dependencies(monkeypatch)
    app = _BulkApp()
    app._bulk_patches = [
        _patch(name="alpha", file_path="/tmp/proj/alpha.sase"),
        _patch(name="beta", file_path="/tmp/proj/beta.sase"),
    ]

    app._launch_resolved_prompt("shared prompt")

    stack = app._session_launch_records
    assert len(stack) == 1
    record = stack[0]
    assert record.proc_ids == ("proc-1", "proc-2")
    assert record.prompt == "shared prompt"
    assert record.context.display_name == "bulk 2 Patches"
    assert record.submitted_prompts == {
        "proc-1": "#gh:alpha shared prompt",
        "proc-2": "#gh:beta shared prompt",
    }
    stamp_launch_record_results(app, "proc-1", (_result("alpha"),))
    assert record.state is LaunchRecordState.IN_FLIGHT
    stamp_launch_record_results(app, "proc-2", (_result("beta"),))
    assert record.state is LaunchRecordState.RESOLVED


def test_failed_proc_keeps_record_resolved_when_successful_results_exist() -> None:
    app = SimpleNamespace()
    record = push_launch_record(
        app,
        proc_ids=("one", "two"),
        prompt="prompt",
        context=_context(),
    )

    stamp_launch_record_results(app, "one", (_result("one"),))
    stamp_launch_record_failure(app, "two")

    assert record is not None
    assert record.results["one"] == (_result("one"),)
    assert record.failed_proc_ids == {"two"}
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record


def test_stack_is_bounded_and_drops_oldest() -> None:
    app = SimpleNamespace()

    for index in range(MAX_SESSION_LAUNCH_RECORDS + 2):
        push_launch_record(
            app,
            proc_ids=(f"proc-{index}",),
            prompt=f"prompt-{index}",
            context=_context(str(index)),
        )

    stack = app._session_launch_records
    assert len(stack) == MAX_SESSION_LAUNCH_RECORDS
    assert stack[0].proc_ids == ("proc-2",)
    assert stack[-1].proc_ids == (f"proc-{MAX_SESSION_LAUNCH_RECORDS + 1}",)


def test_latest_live_launch_record_skips_consumed_and_failed_records() -> None:
    app = SimpleNamespace()
    live = push_launch_record(app, proc_ids=("live",), prompt="p", context=_context())
    failed = push_launch_record(
        app,
        proc_ids=("failed",),
        prompt="p",
        context=_context("failed"),
    )
    consumed = push_launch_record(
        app,
        proc_ids=("consumed",),
        prompt="p",
        context=_context("consumed"),
    )

    assert failed is not None
    assert consumed is not None
    stamp_launch_record_failure(app, "failed")
    consume_launch_record(consumed)

    assert latest_live_launch_record(app) is live


def test_kill_pending_survives_result_stamp() -> None:
    app = SimpleNamespace()
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("demo")
    )
    assert record is not None
    record.state = LaunchRecordState.KILL_PENDING

    stamp_launch_record_results(app, "p1", (_result("demo"),))

    assert record.state is LaunchRecordState.KILL_PENDING
    assert record.results["p1"] == (_result("demo"),)


def test_rename_launch_record_proc_id_rewrites_all_proc_keyed_state() -> None:
    timer = object()
    app = SimpleNamespace()
    record = push_launch_record(
        app,
        proc_ids=("pending-one", "pending-two"),
        prompt="shared",
        context=_context("bulk"),
        submitted_prompts={
            "pending-one": "first prompt",
            "pending-two": "second prompt",
        },
    )
    assert record is not None
    record.results["pending-one"] = (_result("one"),)
    record.failed_proc_ids.add("pending-one")
    record.handled_result_keys.add("result-key")
    record.kill_failed_result_keys.add("failed-result-key")
    record.kill_in_progress_result_keys.add("in-progress-result-key")
    app._pending_launch_kill_timers = {
        ("pending-one", "pending-two"): timer,
    }

    renamed = rename_launch_record_proc_id(app, "pending-one", "durable-one")

    assert renamed is record
    assert record.proc_ids == ("durable-one", "pending-two")
    assert list(record.submitted_prompts) == ["durable-one", "pending-two"]
    assert record.submitted_prompts["durable-one"] == "first prompt"
    assert record.results == {"durable-one": (_result("one"),)}
    assert record.failed_proc_ids == {"durable-one"}
    assert app._pending_launch_kill_timers == {
        ("durable-one", "pending-two"): timer,
    }
    assert record.handled_result_keys == {"result-key"}
    assert record.kill_failed_result_keys == {"failed-result-key"}
    assert record.kill_in_progress_result_keys == {"in-progress-result-key"}


def test_rename_launch_record_proc_id_rekeys_bulk_slots_independently() -> None:
    app = SimpleNamespace()
    record = push_launch_record(
        app,
        proc_ids=("pending-one", "pending-two"),
        prompt="shared",
        context=_context("bulk"),
        submitted_prompts={
            "pending-one": "first prompt",
            "pending-two": "second prompt",
        },
    )
    assert record is not None

    rename_launch_record_proc_id(app, "pending-two", "durable-two")
    rename_launch_record_proc_id(app, "pending-one", "durable-one")

    assert record.proc_ids == ("durable-one", "durable-two")
    assert list(record.submitted_prompts.values()) == ["first prompt", "second prompt"]


def test_rename_launch_record_proc_id_without_owner_is_noop() -> None:
    app = SimpleNamespace()
    record = push_launch_record(
        app,
        proc_ids=("pending-one",),
        prompt="prompt",
        context=_context(),
        submitted_prompts={"pending-one": "prompt"},
    )
    assert record is not None
    timer = object()
    app._pending_launch_kill_timers = {("pending-one",): timer}

    assert rename_launch_record_proc_id(app, "missing", "durable") is None
    assert record.proc_ids == ("pending-one",)
    assert record.submitted_prompts == {"pending-one": "prompt"}
    assert app._pending_launch_kill_timers == {("pending-one",): timer}


def test_has_pending_launch_kill_tracks_kill_pending_records() -> None:
    app = SimpleNamespace()
    assert has_pending_launch_kill(app) is False
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("demo")
    )
    assert record is not None
    assert has_pending_launch_kill(app) is False
    record.state = LaunchRecordState.KILL_PENDING
    assert has_pending_launch_kill(app) is True
    consume_launch_record(record)
    assert has_pending_launch_kill(app) is False


def test_completion_stamps_record_before_launch_delta() -> None:
    app = _CompletionApp()
    push_launch_record(
        app,
        proc_ids=("task-1",),
        prompt="prompt",
        context=_context(),
    )

    app._on_launch_proc_complete(
        _completion(
            "task-1",
            _LaunchProcOutcome("Started 1 agent", results=(_result("demo"),)),
        )
    )

    assert app.delta_states == [LaunchRecordState.RESOLVED]
