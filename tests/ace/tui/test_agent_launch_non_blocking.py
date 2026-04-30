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
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agent_workflow._agent_launch import AgentLaunchMixin
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.workspace_provider._hookspec import WorkflowMetadata


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


class _LaunchBodyApp(AgentLaunchMixin):
    """Harness that exercises the real launch body without spawning agents."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.scheduled: list[tuple[Any, tuple[Any, ...]]] = []
        self.launched: list[dict[str, Any]] = []
        self.launch_thread_ids: list[int] = []
        self.refresh_count = 0
        self._prompt_context: PromptContext | None = _launch_body_context()
        self._bulk_changespecs = None
        self._last_custom_agent_selection = None

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def call_later(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        del kwargs
        self.scheduled.append((fn, args))

    def _try_execute_workflow(
        self, prompt: str, *, has_vcs_ref: bool = False
    ) -> bool | str:
        del prompt, has_vcs_ref
        return False

    def _resolve_vcs_from_prompt(
        self, prompt: str, wf_name: str, *, skip_workspace: bool = False
    ) -> None:
        del prompt, wf_name, skip_workspace
        return None

    def _schedule_agents_async_refresh(self) -> None:
        self.refresh_count += 1

    def _launch_background_agent(self, **kwargs: Any) -> None:
        self.launch_thread_ids.append(threading.get_ident())
        self.launched.append(kwargs)


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


def _launch_body_context() -> PromptContext:
    ctx = _fake_context()
    ctx.is_home_mode = False
    return ctx


def _run_launch_body_with_common_patches(app: _LaunchBodyApp, prompt: str) -> None:
    with ExitStack() as stack:
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
        stack.enter_context(patch("sase.history.prompt.add_or_update_prompt"))
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )
        app._run_agent_launch_body(prompt)


def _cd_metadata() -> tuple[WorkflowMetadata, ...]:
    return (
        WorkflowMetadata(
            workflow_type="cd",
            ref_pattern=r"(?:^|(?<=\s))#cd(?:[_:]([^\s()]+)|\(([^)]*)\))",
            display_name="Directory",
            pre_allocated_env_prefix="SASE_CD",
        ),
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
    assert app.notifications == [("Launching agent for test...", None)]


def test_run_agent_launch_body_skips_xprompt_processing_for_plain_prompt() -> None:
    app = _LaunchBodyApp()
    body_thread_id = threading.get_ident()

    with patch("sase.xprompt.processor.process_xprompt_references") as process:
        _run_launch_body_with_common_patches(app, "plain single-agent prompt")

    process.assert_not_called()
    assert len(app.launched) == 1
    assert app.launched[0]["prompt"] == "plain single-agent prompt"
    assert app.launch_thread_ids == [body_thread_id]
    refresh_calls = [
        (fn, args)
        for fn, args in app.scheduled
        if fn == app._schedule_agents_async_refresh
    ]
    assert len(refresh_calls) == 1


def test_run_agent_launch_body_expands_possible_xprompt_for_model_dispatch() -> None:
    app = _LaunchBodyApp()

    with patch(
        "sase.xprompt.processor.process_xprompt_references",
        return_value="%m(opus,sonnet)\nReview this code",
    ) as process:
        _run_launch_body_with_common_patches(app, "Review this with #swarm")

    process.assert_called_once()
    assert app.launched == []
    multi_model_calls = [
        (fn, args) for fn, args in app.scheduled if fn == app._launch_multi_model_agents
    ]
    assert len(multi_model_calls) == 1


def test_run_agent_launch_body_direct_single_agent_refreshes_after_success() -> None:
    app = _LaunchBodyApp()

    _run_launch_body_with_common_patches(app, "plain single-agent prompt")

    assert len(app.launched) == 1
    scheduled_fns = [fn for fn, _ in app.scheduled]
    assert scheduled_fns.count(app._schedule_agents_async_refresh) == 1
    assert any(
        callable(fn) and fn != app._schedule_agents_async_refresh
        for fn in scheduled_fns
    )


def test_run_agent_launch_body_cd_keeps_home_mode_and_uses_target_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()

    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )

    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: resolve_ref_from_prompt(
            prompt, wf_name, skip_workspace=skip_workspace
        )
    )

    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _cd_metadata)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(patch("sase.history.prompt.add_or_update_prompt"))
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )
        stack.enter_context(
            patch("sase.ace.last_agent_selection.save_last_agent_selection")
        )
        app._run_agent_launch_body(f"#cd:{tmp_path} do work")

    assert len(app.launched) == 1
    launch = app.launched[0]
    assert launch["workspace_dir"] == str(tmp_path.resolve())
    assert launch["workspace_num"] == 0
    assert launch["is_home_mode"] is True
    assert launch["update_target"] == ""
    assert launch["vcs_ref"] == ("cd", str(tmp_path))


def test_run_agent_launch_body_no_ref_defaults_home_mode_to_cd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _LaunchBodyApp()
    app._prompt_context = _fake_context()

    from sase.ace.tui.actions.agent_workflow._ref_resolution import (
        resolve_ref_from_prompt,
    )

    app._resolve_vcs_from_prompt = (  # type: ignore[method-assign]
        lambda prompt, wf_name, skip_workspace=False: resolve_ref_from_prompt(
            prompt, wf_name, skip_workspace=skip_workspace
        )
    )

    import sase.workspace_provider._registry as registry

    monkeypatch.setattr(registry, "get_all_workflow_metadata", _cd_metadata)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.axe.run_agent_phases.resolve_agent_refs_in_prompt",
                side_effect=lambda p: (p, None),
            )
        )
        stack.enter_context(patch("sase.history.prompt.add_or_update_prompt"))
        stack.enter_context(
            patch(
                "sase.history.file_references.extract_recordable_file_refs",
                return_value=[],
            )
        )
        stack.enter_context(
            patch("sase.history.file_references.record_file_references")
        )
        stack.enter_context(
            patch("sase.ace.last_agent_selection.save_last_agent_selection")
        )
        app._run_agent_launch_body("do work")

    assert len(app.launched) == 1
    launch = app.launched[0]
    assert launch["prompt"] == "#cd:~ do work"
    assert launch["workspace_dir"] == str(Path.home().resolve())
    assert launch["workspace_num"] == 0
    assert launch["is_home_mode"] is True
    assert launch["update_target"] == ""
    assert launch["vcs_ref"] == ("cd", "~")
