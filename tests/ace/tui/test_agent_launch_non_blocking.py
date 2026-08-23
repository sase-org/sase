"""Tests that ACE launch submit stays off the event loop.

The prompt-submit path hands the prompt to the durable ``sase run`` proc
queue, which makes the launch visible in the proc indicator and never
runs the retired in-process launch body on the Textual event-loop thread.

Forced-reuse rewrite/wipe coverage lives at the durable seam:
``tests/test_force_reuse_launch_seam.py`` and
``tests/agent/test_force_reuse_launch.py``.
"""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.actions.agent_workflow._launch_procs import (
    _launch_outcome_from_completion,
)
from sase.ace.tui.proc_observer import ObservedProc as ProcInfo
from tests.ace.tui._agent_launch_helpers import _FakeApp


def test_launch_task_completion_emits_warning_messages() -> None:
    app = _FakeApp()
    toast = "Unknown xprompt reference(s): #reviewww"

    app._on_launch_proc_complete(
        TrackedProcCompletion(
            proc_info=ProcInfo(
                proc_id="task",
                proc_type="launch",
                cl_name="test",
                project_file="/tmp/test.sase",
                status="success",
                message="",
                started_at=datetime.now(),
            ),
            success=True,
            message="",
            output="",
            payload={"warning_messages": [toast]},
            error=None,
        )
    )

    assert app.notifications == [(toast, "warning")]


def test_launch_outcome_from_completion_reads_warning_messages_payload() -> None:
    toast = "Unknown xprompt reference(s): #reviewww - passed through as literal text"
    completion = TrackedProcCompletion(
        proc_info=ProcInfo(
            proc_id="task",
            proc_type="launch",
            cl_name="test",
            project_file="/tmp/test.sase",
            status="success",
            message="Started 1 agent(s)",
            started_at=datetime.now(),
        ),
        success=True,
        message="Started 1 agent(s)",
        output="",
        payload={"warning_messages": [toast]},
        error=None,
    )

    outcome = _launch_outcome_from_completion(completion)

    assert outcome is not None
    assert outcome.warning_messages == (toast,)


def test_launch_outcome_from_completion_accepts_proc_only_payload() -> None:
    completion = TrackedProcCompletion(
        proc_info=ProcInfo(
            proc_id="task",
            proc_type="launch",
            cl_name="test",
            project_file="/tmp/test.sase",
            status="success",
            message="Launched 1 of 1 launch unit",
            started_at=datetime.now(),
        ),
        success=True,
        message="Launched 1 of 1 launch unit",
        output="",
        payload={
            "count": 0,
            "pids": [],
            "results": [],
            "request_agents_refresh": True,
            "schedule_agents_refresh": True,
            "admission_complete": True,
            "plan_digest": "a" * 64,
            "admission_summary": {
                "total": 1,
                "eligible": 1,
                "launched": 1,
                "skipped": 0,
                "condition_errors": 0,
                "launch_errors": 0,
            },
            "unit_results": [
                {"logical_id": "unit-1", "outcome": "launched", "identity": "proc-1"}
            ],
        },
        error=None,
    )

    outcome = _launch_outcome_from_completion(completion)

    assert outcome is not None
    assert outcome.results == ()
    assert outcome.request_agents_refresh is True
    assert outcome.schedule_agents_refresh is True
    assert outcome.message == "Launched 1 of 1 launch unit"
    assert outcome.severity is None


def test_launch_task_completion_emits_warning_messages_from_result_payload() -> None:
    app = _FakeApp()
    toast = "Unknown xprompt reference(s): #reviewww - passed through as literal text"

    app._on_launch_proc_complete(
        TrackedProcCompletion(
            proc_info=ProcInfo(
                proc_id="task",
                proc_type="launch",
                cl_name="test",
                project_file="/tmp/test.sase",
                status="success",
                message="Started 1 agent(s)",
                started_at=datetime.now(),
            ),
            success=True,
            message="Started 1 agent(s)",
            output="",
            payload={"warning_messages": [toast]},
            error=None,
        )
    )

    assert (toast, "warning") in app.notifications


def test_finish_agent_launch_schedules_async_body_not_inline_call() -> None:
    """``_finish_agent_launch`` must submit a tracked launch, not run it.

    Inline launch work would re-introduce the event-loop block.
    """
    app = _FakeApp()

    app._finish_agent_launch("the prompt")

    assert app.scheduled == []
    assert len(app.launch_tasks) == 1
    task = app.launch_tasks[0]
    assert task["display_name"] == "launch test"
    assert task["cl_name"] == "test"
    assert task["project_file"] == "/tmp/test.sase"
    assert task["prompt"] == "the prompt"
    assert task["submitted_prompt"] == "the prompt"
    assert app.notifications == [("Launching agent for test...", None)]


def test_finish_agent_launch_force_reuse_submits_raw_prompt_unrewritten() -> None:
    """The submitted ``%id:!`` prompt reaches the proc queue untouched.

    Rewriting the ``!`` and wiping the reserved name happen in the durable
    ``sase run`` child process (see ``sase.agent.force_reuse_launch`` and
    ``launch_query()``), so ``_launch_resolved_prompt`` must hand off the
    raw prompt with ``!`` intact. See
    ``tests/test_force_reuse_launch_seam.py`` for the boundary that
    actually runs.
    """
    app = _FakeApp()

    app._finish_agent_launch("%id:!foo\nDo work")

    assert app.scheduled == []
    assert len(app.launch_tasks) == 1
    task = app.launch_tasks[0]
    assert task["prompt"] == "%id:!foo\nDo work"
    assert task["submitted_prompt"] == "%id:!foo\nDo work"
    assert task["display_name"] == "launch test"
    assert task["cl_name"] == "test"
    assert task["project_file"] == "/tmp/test.sase"
    assert app.notifications == [("Launching agent for test...", None)]
    assert app._prompt_context is None
