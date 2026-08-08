"""Handler for ``sase launch`` approval commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sase.agent.launch_request import LaunchRequestCreationResult, LaunchRequestError
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
                    "reject",
                    feedback=getattr(args, "feedback", None),
                )
            )
            sys.exit(0)
        if subcommand == "request":
            request = _create_request_from_cli(args)
            from sase.agent.launch_request import (
                cancel_launch_approval_request,
                running_agent_context_requires_launch_approval,
                wait_for_launch_approval,
            )

            if running_agent_context_requires_launch_approval():
                try:
                    outcome = wait_for_launch_approval(request)
                except KeyboardInterrupt:
                    try:
                        cancel_launch_approval_request(request)
                    except LaunchRequestError:
                        pass
                    Console(stderr=True).print(
                        "[yellow]Launch request cancelled[/yellow]"
                    )
                    sys.exit(130)
                _print_wait_result(outcome.to_dict(), args.output)
            else:
                _print_request_result(request, args.output)
            sys.exit(0)
    except LaunchApprovalActionError as exc:
        Console(stderr=True).print(f"[red]Error:[/red] {exc}")
        sys.exit(2)
    except LaunchRequestError as exc:
        Console(stderr=True).print(f"[red]Error:[/red] {exc}")
        sys.exit(2)

    print("Usage: sase launch {approve,reject,request}", file=sys.stderr)
    sys.exit(1)


def _create_request_from_cli(args: argparse.Namespace) -> LaunchRequestCreationResult:
    from sase.agent.launch_request import create_launch_approval_request

    payload = _launch_request_payload_from_args(args)
    return create_launch_approval_request(
        payload,
        source_surface=getattr(args, "source", None),
    )


def _launch_request_payload_from_args(args: argparse.Namespace) -> dict[str, Any]:
    payload_arg = getattr(args, "payload", None)
    payload_file = getattr(args, "payload_file", None)
    prompt = getattr(args, "prompt", None)
    if payload_arg and payload_file:
        raise LaunchRequestError(
            "invalid_request", "payload", "pass either PAYLOAD or --file, not both"
        )
    if payload_file:
        return _read_payload_file(Path(payload_file))
    if payload_arg:
        if payload_arg.startswith("@"):
            return _read_payload_file(Path(payload_arg[1:]))
        return _parse_payload_json(payload_arg, "payload")
    if not prompt:
        raise LaunchRequestError(
            "invalid_request", "prompt", "pass a JSON payload or --prompt"
        )
    return {
        "schema_version": 1,
        "prompt": prompt,
        "reason": getattr(args, "reason", None) or "Detached launch requested.",
        "approval": getattr(args, "approval", "required"),
        "max_slots": getattr(args, "max_slots", 1),
    }


def _read_payload_file(path: Path) -> dict[str, Any]:
    try:
        return _parse_payload_json(path.read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        raise LaunchRequestError(
            "invalid_request", str(path), f"failed to read launch request: {exc}"
        ) from exc


def _parse_payload_json(raw: str, target: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LaunchRequestError(
            "invalid_request", target, f"invalid launch request JSON: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise LaunchRequestError(
            "invalid_request", target, "launch request JSON must be an object"
        )
    return payload


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


def _print_request_result(result: LaunchRequestCreationResult, output: str) -> None:
    from rich.console import Console

    request_id = result.request_id
    payload = {
        "request_id": request_id,
        "notification_id": result.notification_id,
        "response_dir": str(result.response_dir),
        "request_file": str(result.request_path),
        "preview_file": str(result.preview_path),
        "response_file": str(result.response_path),
    }
    if output == "json":
        print(json.dumps(payload, sort_keys=True))
        return
    Console().print(
        f"[green]Launch approval requested[/green] "
        f"[bold]{request_id}[/bold] [dim]{_display_path(Path(payload['response_dir']))}[/dim]"
    )


def _print_wait_result(payload: dict[str, Any], output: str) -> None:
    from rich.console import Console

    if output == "json":
        print(json.dumps(payload, sort_keys=True))
        return
    status = str(payload.get("status") or "resolved").replace("_", " ")
    message = str(payload.get("message") or status)
    Console().print(f"[green]{status.title()}[/green] [dim]{message}[/dim]")


def _display_path(path: Path) -> str:
    try:
        return str(path).replace(str(Path.home()), "~")
    except RuntimeError:
        return str(path)


__all__ = ["handle_launch_command"]
