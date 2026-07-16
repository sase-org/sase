"""Shared harness helpers for tracked kill/dismiss cleanup-task tests.

The kill/dismiss persistence stage is submitted through
``CleanupTaskMixin._submit_cleanup_task`` -> ``_submit_tracked_task``. Test
harnesses mix in :class:`TrackedTaskRecorderMixin` to record those
submissions, and :func:`run_tracked_task` replays a recorded task body and
its completion callback synchronously (including any coroutine callbacks the
completion schedules via ``call_later``, e.g. the off-thread
notification-count refresh).
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime
from typing import Any

from sase.ace.tui.actions.task_actions import TrackedTaskCompletion
from sase.ace.tui.task_queue import TaskInfo


class TrackedTaskRecorderMixin:
    """Records ``_submit_tracked_task`` calls for later synchronous replay."""

    tracked_tasks: list[dict[str, Any]]

    def _init_tracked_task_recorder(self) -> None:
        self.tracked_tasks = []

    def _submit_tracked_task(
        self,
        task_type: str,
        cl_name: str,
        project_file: str,
        task_callable: Any,
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> TaskInfo:
        del duplicate_message
        task_info = TaskInfo(
            task_id=f"task-{len(self.tracked_tasks)}",
            task_type=task_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="",
            started_at=datetime(2026, 1, 1, 12, 0, 0),
            display_name=display_name,
            dedup_key=dedup_key,
        )
        self.tracked_tasks.append(
            {
                "task_type": task_type,
                "cl_name": cl_name,
                "project_file": project_file,
                "task_callable": task_callable,
                "display_name": display_name,
                "dedup_key": dedup_key,
                "on_complete": on_complete,
                "reload_on_complete": reload_on_complete,
                "notify_on_complete": notify_on_complete,
                "task_info": task_info,
            }
        )
        return task_info


def run_tracked_task(app: Any, task: dict[str, Any]) -> TrackedTaskCompletion[Any]:
    """Run a recorded task body, fire its completion, and drain async effects."""
    result = task["task_callable"]()
    task_info = task["task_info"]
    task_info.status = "success" if result.success else "error"
    task_info.message = result.message
    completion: TrackedTaskCompletion[Any] = TrackedTaskCompletion(
        task_info=task_info,
        success=result.success,
        message=result.message,
        output="",
        payload=result.payload,
        error=result.error,
    )

    async def _run_completion_effects() -> None:
        on_complete = task["on_complete"]
        if on_complete is not None:
            on_complete(completion)

        # New completion effects use retained pump-free tasks. Drain until
        # stable because a coalesced completion may spawn one follow-up.
        while tasks := list(getattr(app, "_pump_free_async_tasks", ())):
            await asyncio.gather(*tasks)
            await asyncio.sleep(0)

        # Keep compatibility for unrelated synchronous test doubles that
        # intentionally record coroutine callbacks in ``_scheduled``.
        scheduled = getattr(app, "_scheduled", None)
        if scheduled is not None:
            for entry in list(scheduled):
                callback, args = entry
                if inspect.iscoroutinefunction(callback):
                    await callback(*args)
                    scheduled.remove(entry)

    asyncio.run(_run_completion_effects())
    return completion
