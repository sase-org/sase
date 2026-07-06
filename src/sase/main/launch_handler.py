"""Handler for ``sase launch`` approval commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sase.launch_approval_actions import (
    LaunchApprovalActionError,
    LaunchApprovalActionResult,
    execute_launch_approval_response,
    launch_context_from_notification,
)
from sase.notifications.models import Notification
from sase.notifications.pending_actions import action_state_for_notification
from sase.notifications.store import load_notifications


def handle_launch_command(args: argparse.Namespace) -> None:
    """Dispatch ``sase launch`` subcommands."""
    from rich.console import Console

    subcommand = getattr(args, "launch_subcommand", None)
    try:
        if subcommand == "approve":
            _print_result(_resolve_launch_from_cli(args.selector, "approve"))
            sys.exit(0)
        if subcommand == "reject":
            _print_result(
                _resolve_launch_from_cli(
                    args.selector,
                    "reject" if not getattr(args, "feedback", None) else "feedback",
                    feedback=getattr(args, "feedback", None),
                )
            )
            sys.exit(0)
    except LaunchApprovalActionError as exc:
        Console(stderr=True).print(f"[red]Error:[/red] {exc}")
        sys.exit(2)

    print("Usage: sase launch {approve,reject}", file=sys.stderr)
    sys.exit(1)


def _resolve_launch_from_cli(
    selector: str,
    choice: str,
    *,
    feedback: str | None = None,
) -> LaunchApprovalActionResult:
    notification = _resolve_launch_notification(selector)
    _ensure_launch_notification_available(notification)
    return execute_launch_approval_response(
        launch_context_from_notification(notification),
        choice,
        feedback=feedback,
    )


def _resolve_launch_notification(selector: str) -> Notification:
    notifications = [
        notification
        for notification in load_notifications(include_dismissed=False)
        if notification.action == "LaunchApproval"
    ]
    matches = [
        notification
        for notification in notifications
        if notification.id == selector
        or notification.id.startswith(selector)
        or notification.action_data.get("request_id") == selector
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise LaunchApprovalActionError(
            "ambiguous_prefix", selector, "launch request selector is ambiguous"
        )
    raise LaunchApprovalActionError(
        "not_found", selector, "pending launch approval not found"
    )


def _ensure_launch_notification_available(notification: Notification) -> None:
    if notification.action != "LaunchApproval":
        raise LaunchApprovalActionError(
            "unsupported_action",
            notification.action or "non_action",
            "notification is not a launch approval",
        )
    state = action_state_for_notification(notification)
    if state == "available":
        return
    if state == "already_handled":
        raise LaunchApprovalActionError(
            "conflict_already_handled", notification.id, "action already handled"
        )
    if state == "stale":
        raise LaunchApprovalActionError(
            "gone_stale", notification.id, "action is stale"
        )
    raise LaunchApprovalActionError(
        "invalid_request", notification.id, f"action is {state}"
    )


def _print_result(result: LaunchApprovalActionResult) -> None:
    from rich.console import Console

    path = _display_path(result.response_path)
    Console().print(
        f"[green]{result.message}[/green] "
        f"[dim]{result.notification_id[:8]} -> {path}[/dim]"
    )


def _display_path(path: Path) -> str:
    try:
        return str(path).replace(str(Path.home()), "~")
    except RuntimeError:
        return str(path)


__all__ = ["handle_launch_command"]
