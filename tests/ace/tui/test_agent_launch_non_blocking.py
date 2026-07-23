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

Dispatch routing paths through the body live in
``test_agent_launch_dispatch.py``; VCS-ref resolution paths live under
``agent_launch_vcs/``.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import ExitStack
from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.task_actions import TrackedTaskCompletion
from sase.ace.tui.actions.agent_workflow._launch_tasks import LaunchTaskOutcome
from sase.ace.tui.task_queue import TaskInfo
from tests.ace.tui._agent_launch_helpers import _FakeApp
from tests.ace.tui._agent_launch_helpers import _LaunchBodyApp


class _SubmitLaunchBodyApp(_LaunchBodyApp):
    """Launch-start harness that queues the real launch body."""

    def __init__(self) -> None:
        super().__init__()
        self.unmount_calls: list[str] = []
        self.launch_tasks: list[dict[str, Any]] = []

    def _unmount_prompt_bar_after_submit(self) -> None:
        self.unmount_calls.append("submit")

    def _submit_launch_task(
        self,
        *,
        display_name: str,
        cl_name: str,
        project_file: str,
        task_callable: Any,
        dedup_key: str | None = None,
        submitted_prompt: str | None = None,
    ) -> bool:
        self.launch_tasks.append(
            {
                "display_name": display_name,
                "cl_name": cl_name,
                "project_file": project_file,
                "dedup_key": dedup_key,
                "task_callable": task_callable,
                "submitted_prompt": submitted_prompt,
            }
        )
        return True


def _enter_launch_body_base_patches(stack: ExitStack) -> None:
    stack.enter_context(
        patch(
            "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
            side_effect=lambda p: (p, None),
        )
    )
    stack.enter_context(
        patch("sase.workspace_provider.get_ref_patterns", return_value={})
    )
    stack.enter_context(
        patch("sase.workspace_provider.get_workflow_names", return_value=set())
    )
    stack.enter_context(
        patch(
            "sase.history.file_references.extract_recordable_file_refs",
            return_value=[],
        )
    )
    stack.enter_context(patch("sase.history.file_references.record_file_references"))
    stack.enter_context(
        patch(
            "sase.running_field.get_first_available_axe_workspace",
            return_value=100,
        )
    )
    stack.enter_context(
        patch(
            "sase.running_field.claim_next_axe_workspace",
            return_value=100,
        )
    )
    stack.enter_context(
        patch(
            "sase.running_field.get_workspace_directory_for_num",
            return_value=("/tmp/ws100", None),
        )
    )


def _complete_launch_task(app: _SubmitLaunchBodyApp, outcome: Any) -> None:
    app._on_launch_task_complete(
        TrackedTaskCompletion(
            task_info=TaskInfo(
                task_id="task",
                task_type="launch",
                cl_name="test",
                project_file="/tmp/test.sase",
                status="error" if not outcome.success else "success",
                message=outcome.message,
                started_at=datetime.now(),
            ),
            success=outcome.success,
            message=outcome.message,
            output="",
            payload=outcome,
            error=outcome.message if not outcome.success else None,
        )
    )


def test_launch_task_completion_emits_warning_messages() -> None:
    app = _SubmitLaunchBodyApp()
    outcome = LaunchTaskOutcome(
        "done",
        notify=False,
        warning_messages=("Unknown xprompt reference(s): #reviewww",),
    )

    _complete_launch_task(app, outcome)

    assert app.notifications == [("Unknown xprompt reference(s): #reviewww", "warning")]


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

    def slow_body(prompt: str, ctx: object = None) -> None:
        # Sleeps on a worker thread; the event loop must stay responsive.
        del ctx
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

    def failing_body(prompt: str, ctx: object = None) -> None:
        del prompt, ctx
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


def test_finish_agent_launch_force_reuse_schedules_original_prompt_and_worker_rewrites() -> (
    None
):
    """``%id:!`` cleanup runs in the tracked launch task, not during submit."""
    app = _SubmitLaunchBodyApp()

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
                return_value=["forced-ts"],
            )
        )
        _enter_launch_body_base_patches(stack)
        wipe_names = stack.enter_context(
            patch("sase.agent.launch_validation.wipe_names_for_forced_reuse")
        )
        validate_names = stack.enter_context(
            patch("sase.agent.launch_validation.validate_launch_name_requests")
        )
        save_history = stack.enter_context(
            patch("sase.history.prompt.add_or_update_prompt")
        )
        app._finish_agent_launch("%id:!foo\nDo work")

        wipe_names.assert_not_called()
        validate_names.assert_not_called()
        assert app.scheduled == []
        assert app.launched == []
        assert len(app.launch_tasks) == 1
        task = app.launch_tasks[0]
        assert task["display_name"] == "launch test"
        assert task["cl_name"] == "test"
        assert task["project_file"] == "/tmp/test.sase"
        assert app.notifications == [("Launching agent for test...", None)]
        assert app._prompt_context is not None
        assert app._prompt_context.timestamp == "forced-ts"
        assert app._prompt_context.workflow_name == "ace(run)-forced-ts"

        outcome = task["task_callable"]()

    wipe_names.assert_called_once_with(["foo"])
    for call in validate_names.call_args_list:
        assert call.args == (["%id:foo\nDo work"],)
    save_history.assert_called_once_with("%id:foo\nDo work")
    assert app.launched[0]["prompt"] == "%id:foo\nDo work"
    assert outcome.success is True


def test_finish_agent_launch_forced_family_attach_wipes_exact_member() -> None:
    app = _SubmitLaunchBodyApp()
    prompt = "%id(!code, family=foo, bead=sase-1)\nDo work"
    rewritten = "%id(code, family=foo, bead=sase-1)\nDo work"

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
                return_value=["forced-ts"],
            )
        )
        _enter_launch_body_base_patches(stack)
        wipe_names = stack.enter_context(
            patch("sase.agent.launch_validation.wipe_names_for_forced_reuse")
        )
        validate_names = stack.enter_context(
            patch("sase.agent.launch_validation.validate_launch_name_requests")
        )
        save_history = stack.enter_context(
            patch("sase.history.prompt.add_or_update_prompt")
        )
        stack.enter_context(
            patch(
                "sase.agent.family_attach.prepare_family_attach_launch",
                side_effect=lambda _prompt, context, extra_env, **_kwargs: (
                    context,
                    extra_env,
                ),
            )
        )

        app._finish_agent_launch(prompt)
        outcome = app.launch_tasks[0]["task_callable"]()

    wipe_names.assert_called_once_with(["foo--code"])
    for call in validate_names.call_args_list:
        assert call.args == ([rewritten],)
    save_history.assert_called_once_with(rewritten)
    assert app.launched[0]["prompt"] == rewritten
    assert outcome.success is True


def test_finish_agent_launch_force_reuse_wipes_every_multi_prompt_name() -> None:
    """The worker wipes and rewrites forced names in every submitted segment."""
    app = _SubmitLaunchBodyApp()
    prompt = "%id:!foo\nFirst\n---\n%i:!bar\nSecond\n---\n%id:!baz\nThird"
    rewritten = "%id:foo\nFirst\n---\n%i:bar\nSecond\n---\n%id:baz\nThird"
    rewritten_segments = [
        "%id:foo\nFirst",
        "%i:bar\nSecond",
        "%id:baz\nThird",
    ]

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
                return_value=["forced-ts"],
            )
        )
        _enter_launch_body_base_patches(stack)
        wipe_names = stack.enter_context(
            patch("sase.agent.launch_validation.wipe_names_for_forced_reuse")
        )
        validate_names = stack.enter_context(
            patch("sase.agent.launch_validation.validate_launch_name_requests")
        )
        save_history = stack.enter_context(
            patch("sase.history.prompt.add_or_update_prompt")
        )

        app._finish_agent_launch(prompt)

        wipe_names.assert_not_called()
        assert len(app.launch_tasks) == 1
        assert app.launch_tasks[0]["submitted_prompt"] == prompt

        outcome = app.launch_tasks[0]["task_callable"]()

    wipe_names.assert_called_once_with(["foo", "bar", "baz"])
    validate_names.assert_called_once_with(rewritten_segments)
    save_history.assert_called_once_with(rewritten, allow_short=True)
    assert len(app.scheduled) == 1
    queued_multi = app.scheduled[0][1][0]
    assert queued_multi.segments == rewritten_segments
    assert app.scheduled[0][1][3] == rewritten
    assert outcome.success is True


def test_finish_agent_launch_force_reuse_split_protects_fenced_separator() -> None:
    """A separator inside a fenced block does not create a cleanup segment."""
    app = _SubmitLaunchBodyApp()
    prompt = (
        "%id:!foo\nFirst\n```text\ninside\n---\nstill inside\n```\n"
        "---\n%id:!bar\nSecond"
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
                return_value=["forced-ts"],
            )
        )
        _enter_launch_body_base_patches(stack)
        wipe_names = stack.enter_context(
            patch("sase.agent.launch_validation.wipe_names_for_forced_reuse")
        )
        stack.enter_context(
            patch("sase.agent.launch_validation.validate_launch_name_requests")
        )
        stack.enter_context(patch("sase.history.prompt.add_or_update_prompt"))

        app._finish_agent_launch(prompt)
        outcome = app.launch_tasks[0]["task_callable"]()

    wipe_names.assert_called_once_with(["foo", "bar"])
    assert outcome.success is True


def test_finish_agent_launch_force_reuse_early_parse_failure_does_not_wipe() -> None:
    """Early split failures reach the prompt-parse error path before cleanup."""
    app = _SubmitLaunchBodyApp()
    prompt = (
        "---\nxprompts:\n  badname: content\n---\n"
        "%id:!foo\nFirst\n---\n%id:!bar\nSecond"
    )

    with (
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["forced-ts"],
        ),
        patch("sase.agent.launch_validation.wipe_names_for_forced_reuse") as wipe_names,
    ):
        app._finish_agent_launch(prompt)

        with pytest.raises(ValueError, match="must start with '_'"):
            app.launch_tasks[0]["task_callable"]()

    wipe_names.assert_not_called()
    assert app.scheduled == []


def test_finish_agent_launch_invalid_forced_family_name_does_not_wipe() -> None:
    """Reserved family separators are rejected before forced-reuse cleanup."""
    app = _SubmitLaunchBodyApp()
    prompt = "%id:!foo--plan\nDo work"

    with (
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["forced-ts"],
        ),
        patch("sase.agent.launch_validation.wipe_names_for_forced_reuse") as wipe,
        patch("sase.history.prompt.record_failed_launch_prompt") as record_failed,
    ):
        app._finish_agent_launch(prompt)
        outcome = app.launch_tasks[0]["task_callable"]()

    wipe.assert_not_called()
    record_failed.assert_called_once_with(prompt)
    assert app.launched == []
    assert outcome.message == (
        "Agent name 'foo--plan' cannot contain '--'; double dash is reserved "
        "for agent-family phases."
    )
    assert outcome.severity == "error"


def test_finish_agent_launch_force_reuse_wipe_failure_returns_worker_error() -> None:
    """Wipe failures are task failures and record the original submitted prompt."""
    app = _SubmitLaunchBodyApp()

    with (
        patch(
            "sase.core.agent_launch_facade.reserve_launch_timestamp_batch",
            return_value=["forced-ts"],
        ),
        patch(
            "sase.agent.launch_validation.wipe_names_for_forced_reuse",
            side_effect=RuntimeError("boom"),
        ) as wipe_names,
        patch("sase.history.prompt.record_failed_launch_prompt") as record_failed,
    ):
        app._finish_agent_launch("%id:!foo\nDo work")

        wipe_names.assert_not_called()
        assert len(app.launch_tasks) == 1
        assert app.launched == []
        assert app.notifications == [("Launching agent for test...", None)]

        outcome = app.launch_tasks[0]["task_callable"]()

    wipe_names.assert_called_once_with(["foo"])
    record_failed.assert_called_once_with("%id:!foo\nDo work")
    assert app.launched == []
    assert outcome.message == (
        "Agent name reuse failed - see Logs in SASE Admin Center (#)"
    )
    assert outcome.severity == "error"
    assert outcome.success is False

    _complete_launch_task(app, outcome)
    assert app.notifications == [
        ("Launching agent for test...", None),
        ("Agent name reuse failed - see Logs in SASE Admin Center (#)", "error"),
    ]
