"""Mixin providing background task submission for the TUI app."""

from __future__ import annotations

import logging
from inspect import Parameter, signature
from collections.abc import Callable, Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.project_display_names import humanize_cl_name, humanize_cl_names_in_text

from ..task_queue import TaskInfo, TaskQueue, redirect_print_to
from ..task_subprocess import TaskReporter
from ..widgets.task_indicator import TaskIndicator

if TYPE_CHECKING:
    from ...changespec import ChangeSpec

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrackedTaskResult[T]:
    """Result returned by a tracked background task body."""

    success: bool
    message: str
    payload: T | None = None
    error: str | None = None


@dataclass(frozen=True)
class TrackedTaskCompletion[T]:
    """UI-thread completion record for a tracked background task."""

    task_info: TaskInfo
    success: bool
    message: str
    output: str
    payload: T | None = None
    error: str | None = None


@dataclass(frozen=True)
class _TaskWorkerResult[T]:
    task_id: str
    result: TrackedTaskResult[T]
    output: str


@dataclass(frozen=True)
class _TaskCallbackConfig:
    on_complete: Callable[[TrackedTaskCompletion[Any]], None] | None
    reload_on_complete: bool
    notify_on_complete: bool


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
        self._task_completion_callbacks: dict[str, _TaskCallbackConfig] = {}

    def _update_task_indicator(self) -> None:
        """Update the top-bar task indicator with the current running count."""
        try:
            indicator = self.query_one("#task-indicator", TaskIndicator)  # type: ignore[attr-defined]
            indicator.set_count(self._task_queue.running_count)
        except Exception:
            pass

    def _submit_background_task(
        self,
        task_type: str,
        cl_name: str,
        project_file: str,
        task_callable: Callable[..., tuple[bool, str]],
        on_success: Callable[[], None] | None = None,
    ) -> bool:
        """Submit a task to run in background via run_worker().

        Returns False if a task is already running for this ChangeSpec.
        The callable should return (success, message).
        Output capture (stdout/stderr redirect) is handled automatically.
        """

        def _callable(reporter: TaskReporter) -> TrackedTaskResult[None]:
            success, message = _invoke_task_callable(task_callable, reporter)
            return TrackedTaskResult(
                success=success,
                message=message,
                error=message if not success else None,
            )

        def _on_complete(completion: TrackedTaskCompletion[None]) -> None:
            if not completion.success or on_success is None:
                return
            on_success()

        task_info = self._submit_tracked_task(
            task_type,
            cl_name,
            project_file,
            _callable,
            on_complete=_on_complete if on_success is not None else None,
        )
        return task_info is not None

    def _submit_tracked_task[T](
        self,
        task_type: str,
        cl_name: str,
        project_file: str,
        task_callable: Callable[..., TrackedTaskResult[T]],
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        exclusive_scopes: Collection[str] = (),
        duplicate_message: str | None = None,
        on_complete: Callable[[TrackedTaskCompletion[T]], None] | None = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> TaskInfo | None:
        """Submit a typed task to run in a Textual worker thread.

        Returns None if a running task already exists for the dedup scope.
        Existing ChangeSpec actions keep using :meth:`_submit_background_task`;
        launch and other non-ChangeSpec work can provide ``display_name`` and
        ``dedup_key`` for clean task-queue rows.
        """
        if not hasattr(self, "_task_completion_callbacks"):
            self._task_completion_callbacks = {}
        if not hasattr(self, "_task_workers"):
            self._task_workers = {}

        existing = (
            self._task_queue.get_running_for_key(dedup_key)
            if dedup_key is not None
            else self._task_queue.get_running_for_cl(cl_name)
        )
        if existing is None:
            existing = self._task_queue.get_running_for_scopes(exclusive_scopes)
        if existing is not None:
            msg = duplicate_message or (
                f"A {existing.task_type} task is already running for "
                f"{humanize_cl_name(cl_name)}"
            )
            self.notify(msg, severity="warning")  # type: ignore[attr-defined]
            return None

        task_info = self._task_queue.submit(
            task_type,
            cl_name,
            project_file,
            display_name=display_name,
            dedup_key=dedup_key,
            exclusive_scopes=exclusive_scopes,
        )
        task_id = task_info.task_id

        def _wrapped() -> _TaskWorkerResult[T]:
            """Run the callable with task-local reporting."""
            reporter = TaskReporter(task_info)
            with redirect_print_to(task_info.log):
                try:
                    result = _invoke_task_callable(task_callable, reporter)
                except Exception as exc:
                    log.exception("Background task %s failed", task_id)
                    reporter.log(str(exc), stream="stderr")
                    result = TrackedTaskResult(
                        success=False,
                        message=str(exc),
                        error=str(exc),
                    )
            if result.message:
                marker = "OK" if result.success else "ERROR"
                reporter.log(f"{marker}: {result.message}", stream="result")
            return _TaskWorkerResult(task_id, result, task_info.get_live_output())

        self._task_completion_callbacks[task_id] = _TaskCallbackConfig(
            on_complete=on_complete,  # type: ignore[arg-type]
            reload_on_complete=reload_on_complete,
            notify_on_complete=notify_on_complete,
        )

        worker: Worker[Any] = self.run_worker(  # type: ignore[attr-defined]
            _wrapped, thread=True
        )
        self._task_workers[task_id] = worker
        self._update_task_indicator()
        return task_info

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

        if not isinstance(result, _TaskWorkerResult):
            task_id, success, message, output = result
            result = _TaskWorkerResult(
                task_id,
                TrackedTaskResult(
                    success=success,
                    message=message,
                    error=message if not success else None,
                ),
                output,
            )

        task_id = result.task_id
        task_result = result.result

        # Update TaskQueue
        self._task_queue.complete(
            task_id,
            success=task_result.success,
            message=task_result.message,
            output=result.output,
            error=task_result.error,
        )
        task_info = self._task_queue.get(task_id)
        if task_info is None:
            return
        config = self._task_completion_callbacks.pop(
            task_id,
            _TaskCallbackConfig(
                on_complete=None,
                reload_on_complete=True,
                notify_on_complete=True,
            ),
        )

        # Notify user
        if config.notify_on_complete:
            display_message = humanize_cl_names_in_text(task_result.message)
            if task_result.success:
                self.notify(display_message)  # type: ignore[attr-defined]
            else:
                self.notify(  # type: ignore[attr-defined]
                    f"Task failed: {display_message}",
                    severity="error",
                )

        if config.on_complete is not None:
            try:
                config.on_complete(
                    TrackedTaskCompletion(
                        task_info=task_info,
                        success=task_result.success,
                        message=task_result.message,
                        output=result.output,
                        payload=task_result.payload,
                        error=task_result.error,
                    )
                )
            except Exception:
                log.exception("Background task %s completion callback failed", task_id)

        # Reload the TUI
        if config.reload_on_complete:
            self._reload_and_reposition()  # type: ignore[attr-defined]

        # Clean up worker tracking
        self._task_workers.pop(task_id, None)

        self._update_task_indicator()

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

        config = _TaskCallbackConfig(
            on_complete=None,
            reload_on_complete=True,
            notify_on_complete=True,
        )
        if task_id is not None:
            error_msg = str(worker.error) if worker.error else "Unknown error"
            task_info = self._task_queue.get(task_id)
            output = task_info.get_live_output() if task_info is not None else ""
            if task_info is not None:
                task_info.log.append(f"ERROR: {error_msg}", stream="result")
            self._task_queue.complete(
                task_id,
                success=False,
                message=error_msg,
                output=output,
                error=error_msg,
            )
            if task_info is None:
                task_info = self._task_queue.get(task_id)
            config = self._task_completion_callbacks.pop(
                task_id,
                config,
            )
            if config.notify_on_complete:
                self.notify(  # type: ignore[attr-defined]
                    f"Task failed: {error_msg}",
                    severity="error",
                )
            if config.on_complete is not None and task_info is not None:
                try:
                    config.on_complete(
                        TrackedTaskCompletion(
                            task_info=task_info,
                            success=False,
                            message=error_msg,
                            output=output,
                            error=error_msg,
                        )
                    )
                except Exception:
                    log.exception(
                        "Background task %s completion callback failed", task_id
                    )
            self._task_workers.pop(task_id, None)

        if task_id is None or config.reload_on_complete:
            self._reload_and_reposition()  # type: ignore[attr-defined]
        self._update_task_indicator()

    def _kill_background_task(self, task_id: str) -> bool:
        """Kill a running background task by cancelling its worker.

        Returns True if the task was found and killed.
        """
        worker = self._task_workers.get(task_id)
        if worker is None:
            return False

        task_info = self._task_queue.get(task_id)
        if task_info is not None:
            task_info.terminate_processes()
            task_info.log.append("ERROR: Killed by user", stream="result")

        worker.cancel()

        # Mark as killed in the task queue
        self._task_queue.complete(
            task_id,
            success=False,
            message="Killed by user",
            output=task_info.get_live_output() if task_info is not None else "",
            error="Killed by user",
        )

        # Clean up tracking
        self._task_workers.pop(task_id, None)
        self._task_completion_callbacks.pop(task_id, None)

        self._update_task_indicator()
        return True

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Route worker state changes for background tasks."""
        # Handle task queue workers
        if event.worker in self._task_workers.values():
            if event.state == WorkerState.SUCCESS:
                self._on_task_worker_completed(event.worker)
            elif event.state == WorkerState.ERROR:
                self._on_task_worker_error(event.worker)
            return

        # Handle axe worker (defined in AxeMixin)
        axe_worker = getattr(self, "_axe_worker", None)
        if axe_worker is not None and event.worker is axe_worker:
            if event.state in (WorkerState.SUCCESS, WorkerState.ERROR):
                self._on_axe_worker_done(event.worker, event.state)  # type: ignore[attr-defined]


def _invoke_task_callable[T](
    task_callable: Callable[..., T], reporter: TaskReporter
) -> T:
    if _callable_accepts_reporter(task_callable):
        return task_callable(reporter)
    return task_callable()


def _callable_accepts_reporter(task_callable: Callable[..., object]) -> bool:
    try:
        params = signature(task_callable).parameters.values()
    except (TypeError, ValueError):
        return False
    for param in params:
        if param.kind is Parameter.VAR_POSITIONAL:
            return True
        if param.kind in (
            Parameter.POSITIONAL_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False
