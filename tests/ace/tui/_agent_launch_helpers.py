"""Shared harnesses for live ACE launch-submit tests.

These helpers drive ``_finish_agent_launch`` / ``_submit_launch_proc`` without
a live Textual DOM. Assertions should inspect the recorded prompt and payload,
not a discarded in-process launch body.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agent_workflow._agent_launch import AgentLaunchMixin
from sase.ace.tui.actions.agent_workflow._types import PromptContext
from sase.ace.tui.proc_observer import ObservedProc


class _FakeApp(AgentLaunchMixin):
    """Minimal AgentLaunchMixin harness that records launch submissions."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str | None]] = []
        self.scheduled: list[tuple[Any, tuple[Any, ...]]] = []
        self.pushed_screens: list[tuple[Any, Any]] = []
        self.unmount_calls: list[str] = []
        self.launch_tasks: list[dict[str, Any]] = []
        self.workers: list[dict[str, Any]] = []
        self._prompt_context: PromptContext | None = _fake_context()
        self._bulk_patches = None

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

    def run_worker(self, work: Any, **kwargs: Any) -> Any:
        self.workers.append({"work": work, **kwargs})
        if callable(work):
            work()
        return None

    def call_from_thread(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        callback(*args, **kwargs)

    def _unmount_prompt_bar(self) -> None:
        self.unmount_calls.append("cancel")

    def _unmount_prompt_bar_after_submit(self) -> None:
        self.unmount_calls.append("submit")

    def _submit_launch_proc(
        self,
        *,
        display_name: str,
        cl_name: str,
        project_file: str,
        prompt: str = "",
        dedup_key: str | None = None,
        submitted_prompt: str | None = None,
        extra_payload: Any = None,
    ) -> ObservedProc | None:
        proc_id = f"proc-{len(self.launch_tasks) + 1}"
        self.launch_tasks.append(
            {
                "proc_id": proc_id,
                "display_name": display_name,
                "cl_name": cl_name,
                "project_file": project_file,
                "prompt": prompt,
                "dedup_key": dedup_key,
                "submitted_prompt": submitted_prompt,
                "extra_payload": extra_payload,
            }
        )
        return ObservedProc(
            proc_id=proc_id,
            proc_type="launch",
            cl_name=cl_name,
            project_file=project_file,
            status="pending",
            message=f"{display_name} submitted",
            started_at=datetime.now(),
            display_name=display_name,
            dedup_key=dedup_key,
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
