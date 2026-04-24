"""Tests that the agent-launch body does not block the event loop.

The regression guarded here is ``_run_agent_launch_body`` running
synchronously on the Textual event-loop thread after ``call_after_refresh``.
Its blocking I/O (VCS resolution, history writes, xprompt expansion,
workflow dispatch) swallowed rapid ``j``/``k`` keystrokes entered right
after a launch submit.

The fix routes the body through ``_run_agent_launch_body_async``, which
pushes the synchronous work to ``asyncio.to_thread`` and marshals
UI-touching calls back via ``call_later``. These tests exercise the async
wrapper directly and verify the event loop stays responsive while the
body runs.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agent_workflow._agent_launch import AgentLaunchMixin
from sase.ace.tui.actions.agent_workflow._types import PromptContext


class _FakeApp(AgentLaunchMixin):
    """Minimal AgentLaunchMixin harness for the launch-body tests."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.scheduled: list[tuple[Any, tuple[Any, ...]]] = []
        self.body_calls: list[str] = []
        self._prompt_context: PromptContext | None = _fake_context()
        self._bulk_changespecs = None
        self._last_custom_agent_selection = None

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def call_later(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        del kwargs
        self.scheduled.append((fn, args))

    def _unmount_prompt_bar(self) -> None:
        pass

    def _run_agent_launch_body(self, prompt: str) -> None:
        self.body_calls.append(prompt)


def _fake_context() -> PromptContext:
    return PromptContext(
        project_name="test",
        cl_name="test",
        project_file="/tmp/test.gp",
        workspace_dir="/tmp/ws",
        workspace_num=1,
        workflow_name="ace(run)-ts",
        timestamp="ts",
        history_sort_key="",
        display_name="test",
        update_target="",
        is_home_mode=True,
    )


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

    The body must go through ``call_later(self._run_agent_launch_body_async, ...)``
    so it runs in a worker thread via the async wrapper. Inline invocation
    would re-introduce the event-loop block.
    """
    app = _FakeApp()

    app._finish_agent_launch("the prompt")

    # The unmount happens immediately; then a single call_later is made
    # with the async wrapper as its target.
    assert len(app.scheduled) == 1
    fn, args = app.scheduled[0]
    assert fn == app._run_agent_launch_body_async
    assert args == ("the prompt",)
    # The body itself was NOT called synchronously.
    assert app.body_calls == []
