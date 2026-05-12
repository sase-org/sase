"""Shared harnesses and fixtures for the ``_run_agent_launch_body*`` tests.

These helpers were extracted from ``test_agent_launch_non_blocking.py`` when
that file was split per concern (non-blocking wrapper, dispatch routing,
VCS ref resolution).
"""

from __future__ import annotations

import threading
from contextlib import ExitStack
from typing import Any
from unittest.mock import patch

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


def _cd_git_metadata() -> tuple[WorkflowMetadata, ...]:
    return (
        *_cd_metadata(),
        WorkflowMetadata(
            workflow_type="git",
            ref_pattern=r"(?:^|(?<=\s))#git(?:[_:]([a-zA-Z0-9_./-]+)|\(([^)]+)\))",
            display_name="Git",
            pre_allocated_env_prefix="SASE_GIT",
        ),
    )
