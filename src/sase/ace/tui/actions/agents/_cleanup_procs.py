"""Tracked proc helpers for TUI agent kill/dismiss persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from ..proc_actions import TrackedProcCompletion, TrackedProcResult

CleanupSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class CleanupProcOutcome:
    """UI-thread effects to apply after a cleanup proc completes."""

    message: str
    severity: CleanupSeverity | None = None
    notify: bool = False
    refresh_notifications: bool = False
    schedule_agents_refresh_source: str | None = None

    @property
    def success(self) -> bool:
        """Return whether this outcome should be recorded as proc success."""
        return self.severity != "error"


class CleanupProcMixin:
    """Mixin that routes kill/dismiss persistence through the central proc queue."""

    def _submit_cleanup_proc(
        self,
        *,
        proc_type: str,
        display_name: str,
        cl_name: str,
        project_file: str,
        proc_callable: Callable[[], CleanupProcOutcome],
    ) -> bool:
        """Submit a tracked cleanup proc and return whether it was accepted."""

        def _callable() -> TrackedProcResult[CleanupProcOutcome]:
            outcome = proc_callable()
            return TrackedProcResult(
                success=outcome.success,
                message=outcome.message,
                payload=outcome,
                error=outcome.message if not outcome.success else None,
            )

        proc_info = self._submit_tracked_proc(  # type: ignore[attr-defined]
            proc_type,
            cl_name,
            project_file,
            _callable,
            display_name=display_name,
            # Cleanup procs must never collide with Patch per-Patch dedup
            # (get_running_for_cl) for the same Patch name.
            dedup_key=f"{proc_type}:{uuid4().hex}",
            on_complete=self._on_cleanup_proc_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
        return proc_info is not None

    def _on_cleanup_proc_complete(
        self,
        completion: TrackedProcCompletion[CleanupProcOutcome],
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
    "CleanupProcMixin",
    "CleanupProcOutcome",
]
