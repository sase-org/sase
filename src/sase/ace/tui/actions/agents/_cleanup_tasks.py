"""Tracked task helpers for TUI agent kill/dismiss persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from ..task_actions import TrackedTaskCompletion, TrackedTaskResult

CleanupSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class CleanupTaskOutcome:
    """UI-thread effects to apply after a cleanup task completes."""

    message: str
    severity: CleanupSeverity | None = None
    notify: bool = False
    refresh_notifications: bool = False
    schedule_agents_refresh_source: str | None = None

    @property
    def success(self) -> bool:
        """Return whether this outcome should be recorded as task success."""
        return self.severity != "error"


class CleanupTaskMixin:
    """Mixin that routes kill/dismiss persistence through the central task queue."""

    def _submit_cleanup_task(
        self,
        *,
        task_type: str,
        display_name: str,
        cl_name: str,
        project_file: str,
        task_callable: Callable[[], CleanupTaskOutcome],
    ) -> bool:
        """Submit a tracked cleanup task and return whether it was accepted."""

        def _callable() -> TrackedTaskResult[CleanupTaskOutcome]:
            outcome = task_callable()
            return TrackedTaskResult(
                success=outcome.success,
                message=outcome.message,
                payload=outcome,
                error=outcome.message if not outcome.success else None,
            )

        task_info = self._submit_tracked_task(  # type: ignore[attr-defined]
            task_type,
            cl_name,
            project_file,
            _callable,
            display_name=display_name,
            # Cleanup tasks must never collide with ChangeSpec per-ChangeSpec dedup
            # (get_running_for_cl) for the same ChangeSpec name.
            dedup_key=f"{task_type}:{uuid4().hex}",
            on_complete=self._on_cleanup_task_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
        return task_info is not None

    def _on_cleanup_task_complete(
        self,
        completion: TrackedTaskCompletion[CleanupTaskOutcome],
    ) -> None:
        """Apply cleanup-specific completion effects on the UI thread."""
        outcome = completion.payload
        if outcome is None:
            if not completion.success:
                self.notify(  # type: ignore[attr-defined]
                    f"Cleanup task failed: {completion.message}",
                    severity="error",
                )
            return

        if outcome.notify and outcome.message:
            self.notify(  # type: ignore[attr-defined]
                outcome.message,
                severity=outcome.severity or "information",
            )

        if outcome.schedule_agents_refresh_source is not None:
            self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
                source=outcome.schedule_agents_refresh_source
            )

        if outcome.refresh_notifications:
            # Off-thread refresh: the notifications file is read in a worker
            # thread and the indicator update lands back on the UI thread.
            schedule_refresh = getattr(
                self,
                "_schedule_notification_snapshot_refresh",
                None,
            )
            if callable(schedule_refresh):
                schedule_refresh()
            else:
                # Narrow mixin users/tests may omit the notification-provider
                # coalescer. They still use the same pump-free execution
                # boundary rather than falling back to ``call_later(async)``.
                from ...util.pump_tasks import spawn_pump_free_task

                spawn_pump_free_task(
                    self,
                    self._refresh_notification_count_async(),  # type: ignore[attr-defined]
                    name="sase-cleanup-notification-count-refresh",
                    registry_attr="_pump_free_async_tasks",
                )


__all__ = [
    "CleanupTaskMixin",
    "CleanupTaskOutcome",
]
