"""Launch approval notification modal handling."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sase.notifications import Notification


log = logging.getLogger(__name__)

_LaunchApprovalSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class _LaunchApprovalTaskOutcome:
    """UI-thread effects to apply after a launch approval task completes."""

    message: str
    action: str
    severity: _LaunchApprovalSeverity | None = None
    request_agents_refresh: bool = False
    refresh_notifications: bool = True
    display_name: str | None = None
    cl_name: str | None = None
    project_file: str | None = None

    @property
    def success(self) -> bool:
        """Return whether this outcome should be recorded as task success."""
        return self.severity != "error"


@dataclass(frozen=True)
class _LaunchApprovalTaskMetadata:
    """Display metadata for the launch approval task queue row."""

    display_name: str | None
    cl_name: str | None
    project_file: str | None


def handle_launch_approval(app: object, notification: Notification) -> bool:
    """Show the launch approval modal for a pending launch request."""
    from ...modals import LaunchApprovalModal, LaunchApprovalResult

    from sase.notification_gates.debug import debug_context_from_notification
    from sase.notification_gates.paths import resolve_notification_bundle

    bundle = resolve_notification_bundle(notification)
    if bundle is None:
        app.notify(  # type: ignore[attr-defined]
            "No launch request in notification; press d on the notification to debug",
            severity="warning",
        )
        return False

    if not bundle.request.exists():
        app.notify(  # type: ignore[attr-defined]
            "Launch approval request expired or not found; press d on the notification to debug",
            severity="warning",
        )
        return False

    preview_file = next(
        (path for path in notification.files if path.endswith("launch_preview.md")),
        notification.files[0] if notification.files else None,
    )
    request_id = notification.action_data.get("request_id")

    def on_dismiss(result: object) -> None:
        if result is None or not isinstance(result, LaunchApprovalResult):
            return

        if result.action == "approve":
            _notify_app(app, "Approving launch...")
        elif result.action == "reject":
            _notify_app(app, "Rejecting launch...")
        _submit_launch_approval_task(app, notification, result.action, result.feedback)

    app.push_screen(  # type: ignore[attr-defined]
        LaunchApprovalModal(
            preview_file=preview_file,
            request_id=request_id,
            debug_context=debug_context_from_notification(notification),
        ),
        on_dismiss,
    )
    return True


def _submit_launch_approval_task(
    app: object,
    notification: Notification,
    action: str,
    feedback: str | None,
) -> None:
    """Submit launch approval work through the task queue when available."""
    from sase.ace.tui.actions.proc_actions import TrackedProcResult

    request_id = str(notification.action_data.get("request_id") or notification.id)
    response_dir = str(notification.action_data.get("response_dir") or "")
    display_name = f"{action} launch {request_id}"
    cl_name = f"launch approval {request_id}"
    dedup_key = f"launch-approval:{request_id}"

    def task_body() -> _LaunchApprovalTaskOutcome:
        return _run_launch_approval_task(notification, action, feedback)

    def tracked_body() -> TrackedProcResult[_LaunchApprovalTaskOutcome]:
        outcome = task_body()
        return TrackedProcResult(
            success=outcome.success,
            message=outcome.message,
            payload=outcome,
            error=outcome.message if not outcome.success else None,
        )

    submit = getattr(app, "_submit_tracked_proc", None)
    if callable(submit):
        try:
            proc_info = submit(
                "launch",
                cl_name,
                response_dir,
                tracked_body,
                display_name=display_name,
                dedup_key=dedup_key,
                duplicate_message="Launch approval is already being processed",
                on_complete=lambda completion: _finish_launch_approval_task(
                    app, completion
                ),
                reload_on_complete=False,
                notify_on_complete=False,
            )
            if proc_info is not None:
                return
            return
        except Exception:
            log.debug("Falling back to synchronous launch approval", exc_info=True)

    _finish_launch_approval_outcome(app, task_body())


def _run_launch_approval_task(
    notification: Notification,
    action: str,
    feedback: str | None,
) -> _LaunchApprovalTaskOutcome:
    """Worker-thread body for a resolved LaunchApproval notification."""
    from sase.launch_approval_actions import (
        LaunchApprovalActionError,
        execute_launch_approval_response,
        launch_context_from_notification,
    )

    metadata = _read_launch_approval_task_metadata(notification, action)
    try:
        result = execute_launch_approval_response(
            launch_context_from_notification(notification),
            action,
            feedback=feedback,
        )
    except LaunchApprovalActionError as exc:
        severity: _LaunchApprovalSeverity = (
            "warning" if exc.code == "conflict_already_handled" else "error"
        )
        message = (
            "Launch request was already handled"
            if exc.code == "conflict_already_handled"
            else str(exc)
        )
        return _LaunchApprovalTaskOutcome(
            message=message,
            action=action,
            severity=severity,
            display_name=metadata.display_name,
            cl_name=metadata.cl_name,
            project_file=metadata.project_file,
        )

    return _LaunchApprovalTaskOutcome(
        message=result.message,
        action=action,
        request_agents_refresh=action == "approve",
        display_name=metadata.display_name,
        cl_name=metadata.cl_name,
        project_file=metadata.project_file,
    )


def _read_launch_approval_task_metadata(
    notification: Notification,
    action: str,
) -> _LaunchApprovalTaskMetadata:
    """Read optional launch metadata inside the worker, never on keypress."""
    request_id = str(notification.action_data.get("request_id") or notification.id)
    response_dir = notification.action_data.get("response_dir")
    display_name = f"{action} launch {request_id}"
    cl_name = f"launch approval {request_id}"
    project_file = str(response_dir or "")
    if not response_dir:
        return _LaunchApprovalTaskMetadata(display_name, cl_name, project_file)

    from sase.agent.launch_request import LaunchRequestError, read_launch_request

    try:
        data = read_launch_request(Path(response_dir).expanduser())
    except LaunchRequestError:
        return _LaunchApprovalTaskMetadata(display_name, cl_name, project_file)

    workspace = _first_launch_workspace(data)
    if workspace is not None:
        from sase.project_display_names import (
            humanize_cl_name,
            load_project_display_snapshot,
        )

        display_snapshot = load_project_display_snapshot()
        raw_cl_name = workspace.get("cl_name")
        raw_project_file = workspace.get("project_file")
        project_name = workspace.get("project_name")
        if isinstance(raw_cl_name, str) and raw_cl_name:
            cl_name = raw_cl_name
        if isinstance(raw_project_file, str) and raw_project_file:
            project_file = raw_project_file
        if isinstance(project_name, str) and project_name:
            display_target = display_snapshot.label_for(project_name)
            if isinstance(raw_cl_name, str) and raw_cl_name:
                display_cl_name = humanize_cl_name(
                    raw_cl_name,
                    snapshot=display_snapshot,
                )
                if display_cl_name != raw_cl_name:
                    display_target = display_cl_name
            display_name = f"{action} launch {display_target}"
    return _LaunchApprovalTaskMetadata(display_name, cl_name, project_file)


def _first_launch_workspace(data: dict[str, Any]) -> dict[str, Any] | None:
    slots = data.get("slots")
    if not isinstance(slots, list):
        return None
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        workspace = slot.get("workspace")
        if isinstance(workspace, dict):
            return workspace
    return None


def _finish_launch_approval_task(app: object, completion: object) -> None:
    """Apply launch approval completion effects from the tracked task."""
    outcome = getattr(completion, "payload", None)
    if not isinstance(outcome, _LaunchApprovalTaskOutcome):
        success = bool(getattr(completion, "success", False))
        if not success:
            message = str(
                getattr(completion, "message", "") or "Launch approval failed"
            )
            _notify_app(app, message, severity="error")
        _refresh_notification_count_if_available(app)
        return

    proc_info = getattr(completion, "proc_info", None)
    if proc_info is not None:
        if outcome.display_name:
            proc_info.display_name = outcome.display_name
        if outcome.cl_name:
            proc_info.cl_name = outcome.cl_name
        if outcome.project_file:
            proc_info.project_file = outcome.project_file
    _finish_launch_approval_outcome(app, outcome)


def _finish_launch_approval_outcome(
    app: object,
    outcome: _LaunchApprovalTaskOutcome,
) -> None:
    if outcome.refresh_notifications:
        _refresh_notification_count_if_available(app)
    if outcome.request_agents_refresh:
        _request_launch_agents_refresh(app)
    if outcome.message:
        _notify_app(app, outcome.message, severity=outcome.severity)


def _request_launch_agents_refresh(app: object) -> None:
    request_refresh = getattr(app, "request_agents_refresh", None)
    if callable(request_refresh):
        try:
            request_refresh("launch")
            return
        except TypeError:
            request_refresh()
            return

    schedule_refresh = getattr(app, "_schedule_agents_async_refresh", None)
    if not callable(schedule_refresh):
        return
    try:
        schedule_refresh(source="launch")
    except TypeError:
        schedule_refresh()


def _refresh_notification_count_if_available(app: object) -> None:
    refresh_count = getattr(app, "_refresh_notification_count", None)
    if callable(refresh_count):
        refresh_count()


def _notify_app(
    app: object,
    message: str,
    *,
    severity: _LaunchApprovalSeverity | None = None,
) -> None:
    notify = getattr(app, "notify", None)
    if not callable(notify):
        return
    if severity is None:
        notify(message)
    else:
        notify(message, severity=severity)
