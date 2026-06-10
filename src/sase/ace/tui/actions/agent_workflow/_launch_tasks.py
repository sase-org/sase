"""Tracked task helpers for TUI agent launches."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from ..task_actions import TrackedTaskCompletion, TrackedTaskResult

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult


LaunchSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class LaunchTaskOutcome:
    """UI-thread effects to apply after a launch task completes."""

    message: str
    results: tuple[AgentLaunchResult, ...] = ()
    severity: LaunchSeverity | None = None
    notify: bool = True
    request_agents_refresh: bool = False
    schedule_agents_refresh: bool = False
    refresh_notifications: bool = False

    @property
    def success(self) -> bool:
        """Return whether this outcome should be recorded as task success."""
        return self.severity != "error"


def launch_results_tuple(
    results: Sequence[AgentLaunchResult | None],
) -> tuple[AgentLaunchResult, ...]:
    """Normalize a launch result sequence into a tuple without None values."""
    return tuple(result for result in results if result is not None)


class LaunchTaskMixin:
    """Mixin that routes launch worker bodies through the central task queue."""

    def _submit_launch_task(
        self,
        *,
        display_name: str,
        cl_name: str,
        project_file: str,
        task_callable: Callable[[], LaunchTaskOutcome],
        dedup_key: str | None = None,
    ) -> bool:
        """Submit a tracked launch task and return whether it was accepted."""

        def _callable() -> TrackedTaskResult[LaunchTaskOutcome]:
            outcome = task_callable()
            return TrackedTaskResult(
                success=outcome.success,
                message=outcome.message,
                payload=outcome,
                error=outcome.message if not outcome.success else None,
            )

        task_info = self._submit_tracked_task(  # type: ignore[attr-defined]
            "launch",
            cl_name,
            project_file,
            _callable,
            display_name=display_name,
            dedup_key=dedup_key or f"launch:{uuid4().hex}",
            on_complete=self._on_launch_task_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
        return task_info is not None

    def _on_launch_task_complete(
        self,
        completion: TrackedTaskCompletion[LaunchTaskOutcome],
    ) -> None:
        """Apply launch-specific completion effects on the UI thread."""
        outcome = completion.payload
        if outcome is None:
            if not completion.success:
                self.notify(  # type: ignore[attr-defined]
                    "Launch failed (see log)",
                    severity="error",
                )
            elif completion.message:
                self.notify(completion.message)  # type: ignore[attr-defined]
            return

        if outcome.results:
            self._handle_launch_results_delta(outcome.results)  # type: ignore[attr-defined]

        if outcome.request_agents_refresh:
            self.request_agents_refresh("launch")  # type: ignore[attr-defined]

        if outcome.schedule_agents_refresh:
            self._schedule_agents_async_refresh(source="launch")  # type: ignore[attr-defined]

        if outcome.refresh_notifications:
            _refresh_notification_count_if_available(self)

        if outcome.notify and outcome.message:
            self.notify(  # type: ignore[attr-defined]
                outcome.message,
                severity=outcome.severity,
            )


def _refresh_notification_count_if_available(app: object) -> None:
    refresh = getattr(app, "_refresh_notification_count", None)
    if callable(refresh):
        refresh()


__all__ = [
    "LaunchTaskMixin",
    "LaunchTaskOutcome",
    "launch_results_tuple",
]
