"""Tracked proc helpers for TUI agent launches."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import shlex
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from sase.logs import new_error_id

from ..failure_messages import notify_registered_error
from ..proc_actions import TrackedProcCompletion

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult
    from ...proc_observer import ObservedProc


_LaunchSeverity = Literal["warning", "error"]
_FAILED_LAUNCH_DIAGNOSTIC_TAIL_LINES = 200
_FAILED_LAUNCH_OUTPUT_CHAR_LIMIT = 64 * 1024
_FAILED_LAUNCH_OUTPUT_TRUNCATED_MARKER = "[... older process output truncated ...]\n"


@dataclass(frozen=True)
class _LaunchProcOutcome:
    """UI-thread effects to apply after a launch proc completes."""

    message: str
    results: tuple[AgentLaunchResult, ...] = ()
    severity: _LaunchSeverity | None = None
    warning_messages: tuple[str, ...] = ()
    notify: bool = True
    request_agents_refresh: bool = False
    schedule_agents_refresh: bool = False
    refresh_notifications: bool = False

    @property
    def success(self) -> bool:
        """Return whether this outcome should be recorded as proc success."""
        return self.severity != "error"


def _launch_results_tuple(
    results: Sequence[AgentLaunchResult | None],
) -> tuple[AgentLaunchResult, ...]:
    """Normalize a launch result sequence into a tuple without None values."""
    return tuple(result for result in results if result is not None)


class LaunchProcMixin:
    """Mixin that submits durable ``sase run`` launches through the proc queue."""

    def _submit_launch_proc(
        self,
        *,
        display_name: str,
        cl_name: str,
        project_file: str,
        prompt: str,
        dedup_key: str | None = None,
        submitted_prompt: str | None = None,
        extra_payload: dict[str, object] | None = None,
    ) -> ObservedProc | None:
        """Submit a durable ``sase run`` launch and return its placeholder row.

        ``submitted_prompt`` is launch-specific recovery metadata: if the worker
        dies before returning a :class:`_LaunchProcOutcome` (a payloadless
        failure), the completion handler stashes this prompt so it stays
        recoverable. It is kept off the generic proc-queue contract.
        """
        from ..agent_durable import submit_agent_launch

        workflow = (dedup_key or "").removeprefix("launch:") or uuid4().hex
        proc_info = submit_agent_launch(
            self,
            prompt=prompt,
            workflow=workflow,
            cl_name=cl_name,
            project_file=project_file,
            display_name=display_name,
            extra_payload=extra_payload,
            on_complete=self._on_launch_proc_complete,
        )
        if proc_info is not None and submitted_prompt is not None:
            prompts = getattr(self, "_launch_submitted_prompts", None)
            if prompts is None:
                prompts = {}
                self._launch_submitted_prompts = prompts
            prompts[proc_info.proc_id] = submitted_prompt
        return proc_info

    def _on_launch_proc_complete(
        self,
        completion: TrackedProcCompletion[_LaunchProcOutcome],
    ) -> None:
        """Apply launch-specific completion effects on the UI thread."""
        # The launch worker has finished writing prompt history by now, so any
        # placeholder the user just wrote is on disk. Re-warm here rather than
        # waiting for the next ACE start, so the tag is offered in the next
        # prompt of this session.
        _warm_common_placeholders_if_available(self)
        submitted_prompt = self._pop_launch_submitted_prompt(completion)
        outcome = _launch_outcome_from_completion(completion)
        proc_id = completion.proc_info.proc_id
        if outcome is None:
            from ._launch_records import stamp_launch_record_failure

            stamp_launch_record_failure(self, proc_id)
            if not completion.success:
                error_id = new_error_id()
                _schedule_payloadless_launch_failure_log(
                    self,
                    completion,
                    error_id=error_id,
                    submitted_prompt=submitted_prompt,
                )
                if submitted_prompt is not None:
                    # The worker died before recording the prompt; preserve it
                    # in the stash and refresh the badge off the event loop.
                    self._schedule_failed_launch_prompt_recovery(  # type: ignore[attr-defined]
                        submitted_prompt
                    )
                notify_registered_error(self, "Launch failed", error_id=error_id)
            elif completion.message:
                self.notify(completion.message)  # type: ignore[attr-defined]
            return

        from ._launch_records import (
            stamp_launch_record_failure,
            stamp_launch_record_results,
        )

        stamp_launch_record_results(self, proc_id, outcome.results)
        if not outcome.success:
            stamp_launch_record_failure(self, proc_id)

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
        completion: TrackedProcCompletion[_LaunchProcOutcome],
    ) -> str | None:
        """Remove and return the recovery prompt recorded for this launch proc."""
        prompts = getattr(self, "_launch_submitted_prompts", None)
        if not prompts:
            return None
        return prompts.pop(completion.proc_info.proc_id, None) or prompts.pop(
            completion.proc_info.display_name or "", None
        )


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
    completion: TrackedProcCompletion[_LaunchProcOutcome],
    *,
    error_id: str,
    submitted_prompt: str | None = None,
) -> None:
    """Write payloadless launch proc failures off the Textual event loop."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _log_payloadless_launch_failure(
            completion,
            error_id=error_id,
            submitted_prompt=submitted_prompt,
        )
        return

    task = loop.create_task(
        asyncio.to_thread(
            _log_payloadless_launch_failure,
            completion,
            error_id=error_id,
            submitted_prompt=submitted_prompt,
        )
    )
    tasks = getattr(app, "_launch_failure_log_tasks", None)
    if tasks is None:
        tasks = set()
        app._launch_failure_log_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


def _log_payloadless_launch_failure(
    completion: TrackedProcCompletion[_LaunchProcOutcome],
    *,
    error_id: str,
    submitted_prompt: str | None = None,
) -> None:
    """Persist a launch proc failure when the worker produced no outcome."""
    from sase.logs import log_launch_failure

    proc = completion.proc_info
    message = completion.error or completion.message or "Launch task failed"
    output = _failed_launch_diagnostic_output(completion)
    log_launch_failure(
        kind="single",
        display_name=proc.display_name or proc.cl_name or "launch task",
        exc=RuntimeError(message),
        project=proc.cl_name or None,
        stage="launch_proc",
        proc_id=proc.proc_id,
        proc_type=proc.proc_type,
        project_file=_nonempty_str(proc.project_file),
        prompt_preview=submitted_prompt,
        output=output,
        status=_nonempty_str(proc.status),
        phase=_nonempty_str(proc.phase),
        exit_code=proc.exit_code,
        command=_format_proc_command(proc.command),
        log_path=_nonempty_str(proc.log_path),
        proc_message=_nonempty_str(proc.message),
        error_id=error_id,
    )


def _failed_launch_diagnostic_output(
    completion: TrackedProcCompletion[_LaunchProcOutcome],
) -> str | None:
    """Return bounded process output for a payloadless launch failure."""
    if completion.output:
        return _bound_failed_launch_output(completion.output)
    proc = completion.proc_info
    try:
        from sase.procs import read_proc_log_tail

        output = read_proc_log_tail(
            proc.proc_id,
            _FAILED_LAUNCH_DIAGNOSTIC_TAIL_LINES,
            log_path=proc.log_path or None,
        )
    except (OSError, ValueError):
        return None
    return _bound_failed_launch_output(output)


def _bound_failed_launch_output(output: str) -> str | None:
    """Retain the newest diagnostic output within the failed-launch char limit."""
    if not output:
        return None
    if len(output) <= _FAILED_LAUNCH_OUTPUT_CHAR_LIMIT:
        return output
    marker = _FAILED_LAUNCH_OUTPUT_TRUNCATED_MARKER
    retained_chars = _FAILED_LAUNCH_OUTPUT_CHAR_LIMIT - len(marker)
    if retained_chars <= 0:
        return output[-_FAILED_LAUNCH_OUTPUT_CHAR_LIMIT:]
    return marker + output[-retained_chars:]


def _nonempty_str(value: object) -> str | None:
    """Normalize blank context values so the launch logger omits them."""
    if value is None:
        return None
    text = str(value)
    return text or None


def _format_proc_command(command: Sequence[str] | None) -> str | None:
    if not command:
        return None
    return shlex.join(str(part) for part in command) or None


def _launch_outcome_from_completion(
    completion: TrackedProcCompletion[_LaunchProcOutcome],
) -> _LaunchProcOutcome | None:
    payload = completion.payload
    if isinstance(payload, _LaunchProcOutcome):
        return payload
    if not isinstance(payload, dict):
        return None
    from sase.agent.launch_types import AgentLaunchResult

    results = []
    for item in payload.get("results") or ():
        if not isinstance(item, dict):
            continue
        results.append(
            AgentLaunchResult(
                pid=int(item.get("pid") or 0),
                workspace_num=int(item.get("workspace_num") or 0),
                workspace_dir=str(item.get("workspace_dir") or ""),
                output_path=str(item.get("output_path") or ""),
                project_file=str(item.get("project_file") or ""),
                project_name=str(item.get("project_name") or ""),
                workflow_name=str(item.get("workflow_name") or ""),
                cl_name=str(item.get("cl_name") or ""),
                timestamp=str(item.get("timestamp") or ""),
                artifacts_dir=str(item.get("artifacts_dir") or ""),
                agent_name=item.get("agent_name"),
            )
        )
    severity: _LaunchSeverity | None = None
    if not completion.success:
        severity = "error"
    return _LaunchProcOutcome(
        completion.message,
        results=_launch_results_tuple(results),
        severity=severity,
        warning_messages=_warning_messages_from_payload(payload),
        request_agents_refresh=bool(payload.get("request_agents_refresh")),
        schedule_agents_refresh=bool(payload.get("schedule_agents_refresh")),
        refresh_notifications=bool(payload.get("refresh_notifications")),
    )


def _warning_messages_from_payload(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Read ACE toast strings from a durable ``sase run`` result payload."""
    raw = payload.get("warning_messages")
    if isinstance(raw, str):
        return (raw,) if raw else ()
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)


__all__ = [
    "LaunchProcMixin",
]
