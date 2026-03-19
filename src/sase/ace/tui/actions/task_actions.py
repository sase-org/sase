"""Mixin providing background task submission for the TUI app."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from ..task_queue import TaskQueue, capture_output

if TYPE_CHECKING:
    from ...changespec import ChangeSpec

log = logging.getLogger(__name__)


class TaskActionsMixin:
    """Mixin providing background task submission for the TUI app."""

    # Type hints for AceApp attributes used by this mixin
    changespecs: list[ChangeSpec]
    current_idx: int

    def _init_task_queue(self) -> None:
        """Initialize the task queue and worker tracking map.

        Must be called during AceApp.__init__().
        """
        self._task_queue = TaskQueue()
        self._task_workers: dict[str, Worker[Any]] = {}

    def _submit_background_task(
        self,
        task_type: str,
        cl_name: str,
        project_file: str,
        task_callable: Callable[[], tuple[bool, str]],
        on_success: Callable[[], None] | None = None,
    ) -> bool:
        """Submit a task to run in background via run_worker().

        Returns False if a task is already running for this CL.
        The callable should return (success, message).
        Output capture (stdout/stderr redirect) is handled automatically.
        """
        # Per-CL deduplication
        existing = self._task_queue.get_running_for_cl(cl_name)
        if existing is not None:
            self.notify(  # type: ignore[attr-defined]
                f"A {existing.task_type} task is already running for {cl_name}",
                severity="warning",
            )
            return False

        task_info = self._task_queue.submit(task_type, cl_name, project_file)
        task_id = task_info.task_id

        def _wrapped() -> tuple[str, bool, str, str]:
            """Run the callable with captured output. Returns (task_id, success, message, output)."""
            with capture_output() as buf:
                try:
                    success, message = task_callable()
                except Exception as exc:
                    log.exception("Background task %s failed", task_id)
                    return (task_id, False, str(exc), buf.getvalue())
            return (task_id, success, message, buf.getvalue())

        # Store on_success callback so the state-changed handler can invoke it
        if not hasattr(self, "_task_success_callbacks"):
            self._task_success_callbacks: dict[str, Callable[[], None]] = {}
        if on_success is not None:
            self._task_success_callbacks[task_id] = on_success

        worker: Worker[Any] = self.run_worker(  # type: ignore[attr-defined]
            _wrapped, thread=True
        )
        self._task_workers[task_id] = worker
        return True

    def _on_task_worker_completed(
        self,
        worker: Worker[Any],
    ) -> None:
        """Handle a background-task worker reaching SUCCESS state.

        Called from on_worker_state_changed; updates the TaskQueue, fires
        notifications, and triggers a reload.
        """
        result = worker.result
        if result is None:
            return

        task_id, success, message, output = result

        # Update TaskQueue
        self._task_queue.complete(
            task_id,
            success=success,
            message=message,
            output=output,
            error=message if not success else None,
        )

        # Notify user
        if success:
            self.notify(message)  # type: ignore[attr-defined]
        else:
            self.notify(  # type: ignore[attr-defined]
                f"Task failed: {message}",
                severity="error",
            )

        # Fire on_success callback if provided
        if success:
            cb = getattr(self, "_task_success_callbacks", {}).pop(task_id, None)
            if cb is not None:
                cb()

        # Reload the TUI
        self._reload_and_reposition()  # type: ignore[attr-defined]

        # Clean up worker tracking
        self._task_workers.pop(task_id, None)

    def _on_task_worker_error(
        self,
        worker: Worker[Any],
    ) -> None:
        """Handle a background-task worker reaching ERROR state.

        Called from on_worker_state_changed when the worker itself raised.
        """
        # Find the task_id for this worker
        task_id: str | None = None
        for tid, w in self._task_workers.items():
            if w is worker:
                task_id = tid
                break

        if task_id is not None:
            error_msg = str(worker.error) if worker.error else "Unknown error"
            self._task_queue.complete(
                task_id,
                success=False,
                message=error_msg,
                output="",
                error=error_msg,
            )
            self.notify(  # type: ignore[attr-defined]
                f"Task failed: {error_msg}",
                severity="error",
            )
            self._task_workers.pop(task_id, None)
            getattr(self, "_task_success_callbacks", {}).pop(task_id, None)

        self._reload_and_reposition()  # type: ignore[attr-defined]

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Route worker state changes for background tasks."""
        # Only handle workers we track
        if event.worker not in self._task_workers.values():
            return

        if event.state == WorkerState.SUCCESS:
            self._on_task_worker_completed(event.worker)
        elif event.state == WorkerState.ERROR:
            self._on_task_worker_error(event.worker)
