"""Tests that the agent-launch body does not block the event loop.

The regression guarded here is ``_run_agent_launch_body`` running
synchronously on the Textual event-loop thread after ``call_after_refresh``.
Its blocking I/O (VCS resolution, history writes, xprompt expansion,
workflow dispatch) swallowed rapid ``j``/``k`` keystrokes entered right
after a launch submit.

The direct compatibility wrapper still routes the body through
``asyncio.to_thread``. The prompt-submit path now hands the body to the
central Textual task queue, which runs it in a worker thread and makes the
launch visible in the task indicator and Task Queue modal.

Dispatch routing and VCS-ref resolution paths through the body live in
``test_agent_launch_dispatch.py`` and ``test_agent_launch_vcs.py``.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from tests.ace.tui._agent_launch_helpers import _FakeApp


@pytest.mark.asyncio
async def test_launch_body_runs_in_worker_thread_not_blocking_loop() -> None:
    """While the launch body runs its blocking I/O, the event loop stays live.

    On the old synchronous implementation, the body ran on the event-loop
    thread — so nothing else (including a navigation keypress) could
    progress until it returned.  The async variant pushes the call to
    ``asyncio.to_thread``, leaving the loop free.
    """
    app = _FakeApp()

    slow_done = asyncio.Event()

    def slow_body(prompt: str) -> None:
        # Sleeps on a worker thread; the event loop must stay responsive.
        time.sleep(0.2)
        app.body_calls.append(prompt)

    with patch.object(_FakeApp, "_run_agent_launch_body", side_effect=slow_body):
        task = asyncio.create_task(app._run_agent_launch_body_async("hello"))

        # A coroutine scheduled while the body is blocking must still run
        # promptly — this is the property that "j/k works during launch"
        # depends on.
        await asyncio.sleep(0.05)
        assert not task.done(), (
            "body completed suspiciously fast — test cannot observe "
            "responsiveness during the load"
        )
        slow_done.set()  # sentinel: the loop is processing tasks

        await task

    assert app.body_calls == ["hello"]
    assert slow_done.is_set()


@pytest.mark.asyncio
async def test_launch_body_exception_surfaces_as_error_notification() -> None:
    """Exceptions from the worker are surfaced via notify (error severity)."""
    app = _FakeApp()

    def failing_body(prompt: str) -> None:
        del prompt
        raise RuntimeError("boom")

    with patch.object(_FakeApp, "_run_agent_launch_body", side_effect=failing_body):
        await app._run_agent_launch_body_async("hi")

    error_notifications = [
        msg for msg, severity in app.notifications if severity == "error"
    ]
    assert error_notifications
    assert any("failed" in msg.lower() for msg in error_notifications)


def test_finish_agent_launch_schedules_async_body_not_inline_call() -> None:
    """``_finish_agent_launch`` must schedule the body on the loop, not run it.

    The body must be handed to a tracked launch task. Inline invocation would
    re-introduce the event-loop block.
    """
    app = _FakeApp()

    app._finish_agent_launch("the prompt")

    # The unmount happens immediately; then a tracked launch task is submitted.
    assert app.scheduled == []
    assert len(app.launch_tasks) == 1
    task = app.launch_tasks[0]
    assert task["display_name"] == "launch test"
    assert task["cl_name"] == "test"
    assert task["project_file"] == "/tmp/test.sase"
    # The body itself was NOT called synchronously.
    assert app.body_calls == []
    assert app.notifications == [("Launching agent for test...", None)]
    task["task_callable"]()
    assert app.body_calls == ["the prompt"]


def test_finish_agent_launch_force_reuse_wipes_and_schedules_rewritten_prompt() -> None:
    """``%name:!`` is explicit TUI confirmation and should not push a modal."""
    app = _FakeApp()

    with (
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["forced-ts"],
        ),
        patch("sase.agent.launch_validation.wipe_names_for_forced_reuse") as wipe_names,
    ):
        app._finish_agent_launch("%name:!foo\nDo work")

    wipe_names.assert_called_once_with(["foo"])
    assert app.pushed_screens == []
    assert app.scheduled == []
    assert len(app.launch_tasks) == 1
    task = app.launch_tasks[0]
    assert task["display_name"] == "launch test"
    assert app.body_calls == []
    assert app.notifications == [("Launching agent for test...", None)]
    assert app._prompt_context is not None
    assert app._prompt_context.timestamp == "forced-ts"
    assert app._prompt_context.workflow_name == "ace(run)-forced-ts"
    task["task_callable"]()
    assert app.body_calls == ["%name:foo\nDo work"]


def test_finish_agent_launch_force_reuse_wipe_failure_does_not_schedule() -> None:
    """Wipe failures surface through notify and leave launch unscheduled."""
    app = _FakeApp()

    with (
        patch(
            "sase.agent.launch_validation.wipe_names_for_forced_reuse",
            side_effect=RuntimeError("boom"),
        ) as wipe_names,
        patch("sase.history.prompt.record_failed_launch_prompt") as record_failed,
    ):
        app._finish_agent_launch("%name:!foo\nDo work")

    wipe_names.assert_called_once_with(["foo"])
    record_failed.assert_called_once_with("%name:!foo\nDo work")
    assert app.pushed_screens == []
    assert app.scheduled == []
    assert app.body_calls == []
    assert app.notifications == [
        ("Agent name reuse failed (see log)", "error"),
    ]
