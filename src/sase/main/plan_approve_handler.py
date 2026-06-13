"""Utility functions for plan approval and notification support.

Provides helpers for auto-approve checking, desktop notifications,
and tmux bell ringing. Used by the agent runner and other plan/question
orchestration code.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal, NoReturn

from sase.core.shell import get_vendored_tool
from sase.notifications.models import Notification
from sase.notifications.pending_actions import (
    action_state_for_notification,
    resolve_prefix,
)
from sase.notifications.store import load_notifications
from sase.plan_approval_actions import (
    PlanApprovalActionContext,
    PlanApprovalActionError,
    PlanApprovalActionResult,
    execute_plan_approval_response,
)

PlanAutoApprovalAction = Literal["approve", "epic"]


def _normalize_plan_action(value: object) -> PlanAutoApprovalAction | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized == "approve":
        return "approve"
    if normalized == "epic":
        return "epic"
    return None


def _read_agent_meta() -> dict[str, object]:
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return {}
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def get_auto_plan_approval_action() -> PlanAutoApprovalAction | None:
    """Return the plan-specific auto-approval action, if one is active."""
    for env_name in (
        "SASE_AGENT_AUTO_APPROVE_PLAN_ACTION",
        "SASE_AGENT_AUTO_PLAN_ACTION",
    ):
        action = _normalize_plan_action(os.environ.get(env_name))
        if action is not None:
            return action

    meta = _read_agent_meta()
    action = _normalize_plan_action(meta.get("auto_approve_plan_action"))
    if action is not None:
        return action

    if os.environ.get("SASE_AGENT_AUTO_APPROVE") or meta.get("approve"):
        return "approve"

    return None


def handle_plan_approve_command(args: argparse.Namespace) -> NoReturn:
    """Approve one pending plan proposal from the CLI."""
    from rich.console import Console

    try:
        result = _approve_plan_from_cli(
            selector=getattr(args, "selector", None),
            kind=getattr(args, "kind", "approve"),
            coder_prompt=getattr(args, "prompt", None),
            coder_model=getattr(args, "model", None),
        )
    except PlanApprovalActionError as exc:
        Console(stderr=True).print(f"[red]Error:[/red] {exc}")
        if exc.code in {"missing_selector", "ambiguous_prefix", "not_found"}:
            Console(stderr=True).print(
                "[dim]Run `sase plan list` to see pending plans.[/dim]"
            )
        sys.exit(2)

    Console().print(
        f"[green]{result.message}[/green] "
        f"[dim]{result.notification_id[:8]} -> {result.response_path}[/dim]"
    )
    sys.exit(0)


def _approve_plan_from_cli(
    *,
    selector: str | None,
    kind: str,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
) -> PlanApprovalActionResult:
    """Resolve and approve a pending PlanApproval notification."""
    notification = (
        _resolve_single_pending_plan()
        if selector is None
        else _resolve_plan_selector(selector)
    )
    _ensure_plan_notification_available(notification)
    return execute_plan_approval_response(
        _plan_context_from_notification(notification),
        kind,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
    )


def _resolve_single_pending_plan() -> Notification:
    pending = _available_plan_notifications()
    if not pending:
        raise PlanApprovalActionError(
            "missing_selector",
            "selector",
            "no pending plan proposals; pass a selector after running `sase plan list`",
        )
    if len(pending) > 1:
        raise PlanApprovalActionError(
            "missing_selector",
            "selector",
            "multiple pending plan proposals; pass an ID prefix from `sase plan list`",
        )
    return pending[0]


def _resolve_plan_selector(selector: str) -> Notification:
    identity = resolve_prefix(selector)
    if identity.resolution in {"exact", "unique_prefix"}:
        notification = _notification_by_id(identity.notification_id)
        if notification is not None:
            return notification
    elif identity.resolution in {"ambiguous_prefix", "duplicate_full_id"}:
        raise PlanApprovalActionError(
            "ambiguous_prefix", selector, "action prefix is ambiguous"
        )

    fallback = [
        notification
        for notification in _available_plan_notifications()
        if notification.id == selector or notification.id.startswith(selector)
    ]
    if len(fallback) == 1:
        return fallback[0]
    if len(fallback) > 1:
        raise PlanApprovalActionError(
            "ambiguous_prefix", selector, "action prefix is ambiguous"
        )
    raise PlanApprovalActionError(
        "not_found", selector, "pending plan approval not found"
    )


def _available_plan_notifications() -> list[Notification]:
    return [
        notification
        for notification in load_notifications(include_dismissed=False)
        if notification.action == "PlanApproval"
        and action_state_for_notification(notification) == "available"
    ]


def _notification_by_id(notification_id: str) -> Notification | None:
    for notification in load_notifications(include_dismissed=False):
        if notification.id == notification_id:
            return notification
    return None


def _ensure_plan_notification_available(notification: Notification) -> None:
    if notification.action != "PlanApproval":
        raise PlanApprovalActionError(
            "unsupported_action",
            notification.action or "non_action",
            "notification is not a plan approval",
        )

    state = action_state_for_notification(notification)
    if state == "available":
        return
    if state == "already_handled":
        raise PlanApprovalActionError(
            "conflict_already_handled", notification.id, "action already handled"
        )
    if state == "stale":
        raise PlanApprovalActionError("gone_stale", notification.id, "action is stale")
    raise PlanApprovalActionError(
        "invalid_request", notification.id, f"action is {state}"
    )


def _plan_context_from_notification(
    notification: Notification,
) -> PlanApprovalActionContext:
    return PlanApprovalActionContext(
        id=notification.id,
        host_files=tuple(str(Path(path).expanduser()) for path in notification.files),
        host_action_data={
            key: str(Path(value).expanduser())
            for key, value in notification.action_data.items()
        },
    )


def is_auto_approve_active() -> bool:
    """Check if auto-approve is active via env var or agent_meta.json.

    Returns True if SASE_AGENT_AUTO_APPROVE env var is set, or if the
    ``approve`` field is truthy in the agent's ``agent_meta.json`` (located
    via SASE_ARTIFACTS_DIR).
    """
    return bool(
        os.environ.get("SASE_AGENT_AUTO_APPROVE") or _read_agent_meta().get("approve")
    )


def get_tmux_prefix() -> str:
    """Get the tmux window prefix for notifications."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    project_name = os.path.basename(project_dir)
    prefix = f"[{project_name}]"

    tmux_pane = os.environ.get("TMUX_PANE")
    if tmux_pane:
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-t", tmux_pane, "-p", "#W"],
                capture_output=True,
                text=True,
                check=False,
            )
            window = result.stdout.strip()
            if window:
                prefix = f"[{project_name}#{window}]"
        except FileNotFoundError:
            pass

    return prefix


def send_desktop_notification(title: str, message: str) -> None:
    """Send a desktop notification (cross-platform)."""
    import platform

    if platform.system() == "Darwin":
        subprocess.run(
            ["terminal-notifier", "-title", title, "-message", message],
            check=False,
            capture_output=True,
        )
    else:
        try:
            subprocess.run(
                ["notify-send", title, message],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass


def ring_tmux_bell() -> None:
    """Ring the tmux bell for the window running Claude."""
    tmux_pane = os.environ.get("TMUX_PANE")
    if tmux_pane:
        try:
            subprocess.run(
                [get_vendored_tool("tmux_ring_bell"), tmux_pane],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass
