"""Shared harnesses and fixtures for the ``_run_agent_launch_body*`` tests.

These helpers were extracted from ``test_agent_launch_non_blocking.py`` when
that file was split per concern: non-blocking wrapper, dispatch routing,
and VCS ref resolution.
"""

from __future__ import annotations

import threading
from contextlib import ExitStack
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agent_workflow._agent_launch import AgentLaunchMixin
from sase.ace.tui.actions.agent_workflow._launch_tasks import LaunchTaskOutcome
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.agent.launch_types import AgentLaunchResult


class _FakeApp(AgentLaunchMixin):
    """Minimal AgentLaunchMixin harness for the launch-body tests."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.scheduled: list[tuple[Any, tuple[Any, ...]]] = []
        self.pushed_screens: list[tuple[Any, Any]] = []
        self.body_calls: list[str] = []
        self.body_call_contexts: list[PromptContext | None] = []
        self.unmount_calls: list[str] = []
        self.launch_tasks: list[dict[str, Any]] = []
        self._prompt_context: PromptContext | None = _fake_context()
        self._bulk_patches = None
        self._last_custom_agent_selection = None

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def call_later(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        del kwargs
        self.scheduled.append((fn, args))

    def _schedule_prompt_stash_badge_refresh(self) -> None:
        pass

    def _schedule_failed_launch_prompt_recovery(self, submitted_prompt: str) -> None:
        del submitted_prompt

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self.pushed_screens.append((screen, callback))

    def _unmount_prompt_bar(self) -> None:
        self.unmount_calls.append("cancel")

    def _unmount_prompt_bar_after_submit(self) -> None:
        self.unmount_calls.append("submit")

    def _run_agent_launch_body(
        self, prompt: str, ctx: PromptContext | None = None
    ) -> LaunchTaskOutcome:
        self.body_calls.append(prompt)
        self.body_call_contexts.append(ctx)
        return LaunchTaskOutcome("done", notify=False)

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


class _LaunchBodyApp(AgentLaunchMixin):
    """Harness that exercises the real launch body without spawning agents."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.scheduled: list[tuple[Any, tuple[Any, ...]]] = []
        self.launched: list[dict[str, Any]] = []
        self.launch_delta_batches: list[list[AgentLaunchResult]] = []
        self.delta_artifact_dirs: list[list[str]] = []
        self.launch_thread_ids: list[int] = []
        self.refresh_count = 0
        self._prompt_context: PromptContext | None = _launch_body_context()
        self._bulk_patches = None
        self._last_custom_agent_selection = None

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def call_later(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        del kwargs
        self.scheduled.append((fn, args))

    def _schedule_prompt_stash_badge_refresh(self) -> None:
        pass

    def _schedule_failed_launch_prompt_recovery(self, submitted_prompt: str) -> None:
        del submitted_prompt

    def _try_execute_workflow(
        self,
        prompt: str,
        *,
        has_vcs_ref: bool = False,
        submitted_prompt: str | None = None,
    ) -> bool | str:
        del prompt, has_vcs_ref, submitted_prompt
        return False

    def _resolve_vcs_from_prompt(
        self, prompt: str, wf_name: str, *, skip_workspace: bool = False
    ) -> None:
        del prompt, wf_name, skip_workspace
        return None

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        del source
        self.refresh_count += 1

    def _schedule_agent_artifact_delta_refresh(
        self,
        artifact_dirs: list[Any],
        *,
        source: str = "launch",
    ) -> None:
        del source
        self.delta_artifact_dirs.append([str(path) for path in artifact_dirs])

    def _launch_background_agent(self, **kwargs: Any) -> AgentLaunchResult:
        self.launch_thread_ids.append(threading.get_ident())
        self.launched.append(kwargs)
        return AgentLaunchResult(
            pid=123,
            workspace_num=kwargs["workspace_num"],
            workspace_dir=kwargs["workspace_dir"],
            output_path="/tmp/out.txt",
            project_file=kwargs["project_file"],
            project_name=kwargs["project_name"],
            workflow_name=kwargs["workflow_name"],
            cl_name=kwargs["cl_name"],
            timestamp=kwargs["timestamp"],
        )


def _fake_context() -> PromptContext:
    return PromptContext(
        project_name="test",
        cl_name="test",
        project_file="/tmp/test.sase",
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


def _run_launch_body_with_common_patches(
    app: _LaunchBodyApp, prompt: str
) -> LaunchTaskOutcome:
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
        return app._run_agent_launch_body(prompt)
