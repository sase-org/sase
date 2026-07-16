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
from typing import Literal, NoReturn, cast

from sase.core.shell import get_vendored_tool
from sase.main.plan_pending import (
    ensure_plan_notification_available,
    plan_context_from_notification,
    resolve_pending_plan,
)
from sase.plan_approval_actions import (
    PlanApprovalActionError,
    PlanApprovalActionResult,
    PlanApprovalValidationError,
    execute_plan_approval_response,
)
from sase.plan_approval_choices import PLAN_APPROVAL_AUTO_MODE_CHOICES

PlanAutoApprovalAction = Literal["approve", "epic", "tale"]


def _normalize_plan_action(value: object) -> PlanAutoApprovalAction | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in PLAN_APPROVAL_AUTO_MODE_CHOICES:
        return cast(PlanAutoApprovalAction, normalized)
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
    """Approve one pending plan proposal from the ChangeSpecI."""
    from rich.console import Console

    try:
        result = _approve_plan_from_cli(
            selector=getattr(args, "selector", None),
            kind=getattr(args, "kind", None),
            coder_prompt=getattr(args, "prompt", None),
            coder_model=getattr(args, "model", None),
        )
    except PlanApprovalValidationError as exc:
        from sase.main.plan_validate_render import render_validation_human

        render_validation_human(
            exc.validation,
            tier=exc.tier,
            path=str(exc.plan_path),
            schema=exc.schema,
            console=Console(stderr=True),
        )
        sys.exit(1)
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
    kind: str | None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
) -> PlanApprovalActionResult:
    """Resolve and approve a pending PlanApproval notification."""
    notification = resolve_pending_plan(selector)
    ensure_plan_notification_available(notification)
    return execute_plan_approval_response(
        plan_context_from_notification(notification),
        kind,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
        epic_launch_mode="foreground",
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
