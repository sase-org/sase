"""Tracked proc helpers for TUI agent launches."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from ..failure_messages import with_log_panel_hint
from ..proc_actions import TrackedProcCompletion, TrackedProcResult

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult


LaunchSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class LaunchProcOutcome:
    """UI-thread effects to apply after a launch proc completes."""

    message: str
    results: tuple[AgentLaunchResult, ...] = ()
    severity: LaunchSeverity | None = None
    warning_messages: tuple[str, ...] = ()
    notify: bool = True
    request_agents_refresh: bool = False
    schedule_agents_refresh: bool = False
    refresh_notifications: bool = False

    @property
    def success(self) -> bool:
        """Return whether this outcome should be recorded as proc success."""
        return self.severity != "error"

    def with_warning_messages(
        self,
        warning_messages: Sequence[str],
    ) -> LaunchProcOutcome:
        """Return a copy carrying additional non-fatal warning toasts."""
        if not warning_messages:
            return self
        merged = tuple(dict.fromkeys((*self.warning_messages, *warning_messages)))
        return replace(self, warning_messages=merged)


def launch_results_tuple(
    results: Sequence[AgentLaunchResult | None],
) -> tuple[AgentLaunchResult, ...]:
    """Normalize a launch result sequence into a tuple without None values."""
    return tuple(result for result in results if result is not None)


class LaunchProcMixin:
    """Mixin that routes launch worker bodies through the central proc queue."""

    def _submit_launch_proc(
        self,
        *,
        display_name: str,
        cl_name: str,
        project_file: str,
        proc_callable: Callable[[], LaunchProcOutcome],
        dedup_key: str | None = None,
        submitted_prompt: str | None = None,
    ) -> bool:
        """Submit a tracked launch proc and return whether it was accepted.

        ``submitted_prompt`` is launch-specific recovery metadata: if the worker
        dies before returning a :class:`LaunchProcOutcome` (a payloadless
        failure), the completion handler stashes this prompt so it stays
        recoverable. It is kept off the generic proc-queue contract.
        """

        def _callable() -> TrackedProcResult[LaunchProcOutcome]:
            outcome = proc_callable()
            return TrackedProcResult(
                success=outcome.success,
                message=outcome.message,
                payload=outcome,
                error=outcome.message if not outcome.success else None,
            )

        proc_info = self._submit_tracked_proc(  # type: ignore[attr-defined]
            "launch",
            cl_name,
            project_file,
            _callable,
            display_name=display_name,
            dedup_key=dedup_key or f"launch:{uuid4().hex}",
            on_complete=self._on_launch_proc_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
        if proc_info is not None and submitted_prompt is not None:
            prompts = getattr(self, "_launch_submitted_prompts", None)
            if prompts is None:
                prompts = {}
                self._launch_submitted_prompts = prompts
            prompts[proc_info.proc_id] = submitted_prompt
        return proc_info is not None

    def _on_launch_proc_complete(
        self,
        completion: TrackedProcCompletion[LaunchProcOutcome],
    ) -> None:
        """Apply launch-specific completion effects on the UI thread."""
        # The launch worker has finished writing prompt history by now, so any
        # placeholder the user just wrote is on disk. Re-warm here rather than
        # waiting for the next ACE start, so the tag is offered in the next
        # prompt of this session.
        _warm_common_placeholders_if_available(self)
        submitted_prompt = self._pop_launch_submitted_prompt(completion)
        outcome = completion.payload
        if outcome is None:
            if not completion.success:
                _schedule_payloadless_launch_failure_log(self, completion)
                if submitted_prompt is not None:
                    # The worker died before recording the prompt; preserve it
                    # in the stash and refresh the badge off the event loop.
                    self._schedule_failed_launch_prompt_recovery(  # type: ignore[attr-defined]
                        submitted_prompt
                    )
                self.notify(  # type: ignore[attr-defined]
                    with_log_panel_hint("Launch failed"),
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

        if outcome.severity in ("error", "warning"):
            # A failed/partial worker already stashed its prompt synchronously;
            # refresh the badge so the new row is reflected.
            self._schedule_prompt_stash_badge_refresh()  # type: ignore[attr-defined]

        for warning in outcome.warning_messages:
            self.notify(warning, severity="warning")  # type: ignore[attr-defined]

        if outcome.notify and outcome.message:
            self.notify(  # type: ignore[attr-defined]
                outcome.message,
                severity=outcome.severity,
            )

    def _pop_launch_submitted_prompt(
        self,
        completion: TrackedProcCompletion[LaunchProcOutcome],
    ) -> str | None:
        """Remove and return the recovery prompt recorded for this launch proc."""
        prompts = getattr(self, "_launch_submitted_prompts", None)
        if not prompts:
            return None
        return prompts.pop(completion.proc_info.proc_id, None)


def _warm_common_placeholders_if_available(app: object) -> None:
    warm = getattr(app, "warm_common_placeholders", None)
    if callable(warm):
        warm()


def _refresh_notification_count_if_available(app: object) -> None:
    refresh = getattr(app, "_refresh_notification_count", None)
    if callable(refresh):
        refresh()


def _schedule_payloadless_launch_failure_log(
    app: Any,
    completion: TrackedProcCompletion[LaunchProcOutcome],
) -> None:
    """Write payloadless launch proc failures off the Textual event loop."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _log_payloadless_launch_failure(completion)
        return

    task = loop.create_task(
        asyncio.to_thread(_log_payloadless_launch_failure, completion)
    )
    tasks = getattr(app, "_launch_failure_log_tasks", None)
    if tasks is None:
        tasks = set()
        app._launch_failure_log_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


def _log_payloadless_launch_failure(
    completion: TrackedProcCompletion[LaunchProcOutcome],
) -> None:
    """Persist a launch proc failure when the worker produced no outcome."""
    from sase.logs import log_launch_failure

    proc = completion.proc_info
    message = completion.error or completion.message or "Launch task failed"
    log_launch_failure(
        kind="single",
        display_name=proc.display_name or proc.cl_name or "launch task",
        exc=RuntimeError(message),
        project=proc.cl_name or None,
        stage="launch_proc",
        proc_id=proc.proc_id,
        proc_type=proc.proc_type,
        project_file=proc.project_file,
        output=completion.output or None,
    )


__all__ = [
    "LaunchProcMixin",
    "LaunchProcOutcome",
    "launch_results_tuple",
]
