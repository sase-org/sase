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

from sase.env_contracts import provider_project_dir_from_env
from sase.main.plan_direct_approval import DirectApprovalKind
from sase.main.plan_pending import (
    PendingPlan,
    PendingPlanAmbiguity,
    PendingPlanMatch,
    PendingPlanMiss,
    ensure_plan_notification_available,
    pending_plans,
    plan_context_from_notification,
    resolve_pending_plan_selector,
)
from sase.main.plan_pending_diagnosis import miss_error_code
from sase.main.plan_pending_render import (
    render_ambiguity,
    render_miss,
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
    raw_argument, has_raw_argument = _raw_auto_plan_argument()
    if has_raw_argument:
        if raw_argument == "epic":
            return "epic"
        if raw_argument == "tale":
            return "tale"
        # ``approve`` is an enabled-state compatibility sentinel. The plan
        # adapter receives and validates the opaque argument separately.
        return "approve"
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


def get_auto_plan_approval_argument() -> str | None:
    """Return the optional raw argument retained from ``%auto``."""
    argument, present = _raw_auto_plan_argument()
    return argument if present else None


def _raw_auto_plan_argument() -> tuple[str | None, bool]:
    for env_name in (
        "SASE_AGENT_AUTO_APPROVE_ARGUMENT",
        "SASE_AGENT_AUTO_PLAN_ARGUMENT",
    ):
        if env_name in os.environ:
            value = os.environ.get(env_name, "").strip()
            return value or None, True
    meta = _read_agent_meta()
    if "auto_approve_argument" in meta:
        raw_value = meta.get("auto_approve_argument")
        if isinstance(raw_value, str):
            return raw_value.strip() or None, True
    return None, False


def handle_plan_approve_command(args: argparse.Namespace) -> NoReturn:
    """Approve a live proposal or a plan file through one CLI command."""
    from rich.console import Console

    try:
        result = _approve_plan_from_cli(
            selector=getattr(args, "selector", None),
            kind=getattr(args, "kind", None),
            coder_prompt=getattr(args, "prompt", None),
            coder_model=getattr(args, "model", None),
            wait=getattr(args, "wait", None),
            dry_run=bool(getattr(args, "dry_run", False)),
            project=getattr(args, "project", None),
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
        if not getattr(exc, "_sase_rendered", False):
            from sase.main.plan_approve_render import render_approval_error

            render_approval_error(exc)
        sys.exit(2)
    except Exception as exc:
        from sase.main.plan_direct_approval import DirectApprovalRefused

        if isinstance(exc, DirectApprovalRefused):
            from sase.main.plan_approve_render import render_direct_approval_refusal

            render_direct_approval_refusal(exc.refusal)
            sys.exit(2)
        raise

    if (
        isinstance(result, PlanApprovalActionResult)
        and result.epic_launch_monitor_id is not None
    ):
        monitor_id = result.epic_launch_monitor_id
        Console().print(
            f"[cyan]Monitor {monitor_id}[/cyan] "
            f"[dim]Follow with `sase monitor show {monitor_id} --follow`.[/dim]"
        )
    elif (
        isinstance(result, PlanApprovalActionResult)
        and result.epic_launch_task_id is not None
    ):
        task_id = result.epic_launch_task_id
        Console().print(
            f"[cyan]Proc {task_id}[/cyan] "
            f"[dim]Follow with `sase proc show {task_id} --follow`.[/dim]"
        )
    if getattr(result, "coder_error", None) or getattr(result, "incomplete", False):
        sys.exit(1)
    sys.exit(0)


def _approve_plan_from_cli(
    *,
    selector: str | None,
    kind: str | None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
    wait: str | None = None,
    dry_run: bool = False,
    project: str | None = None,
) -> PlanApprovalActionResult | object | None:
    """Route a selector to a live gate or a file-backed direct approval."""
    _validate_wait_spec_for_cli(wait)
    outcome = resolve_pending_plan_selector(selector)
    if isinstance(outcome, PendingPlanMatch):
        return _approve_pending_plan(
            outcome.plan,
            selector=selector,
            kind=kind,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            wait=wait,
            dry_run=dry_run,
            project=project,
        )
    if isinstance(outcome, PendingPlanAmbiguity):
        render_ambiguity(outcome, pending_plans())
        raise _rendered_error(
            "ambiguous_prefix", outcome.selector, "action prefix is ambiguous"
        )
    if selector is None or not selector.strip():
        _render_omitted_direct_approval_miss(outcome)
        raise _rendered_error("missing_selector", "selector", outcome.header)

    from sase.main.plan_direct_approval import (
        DirectApprovalRefusal,
        DirectApprovalRefused,
        DirectApprovalRequest,
        resolve_direct_approval,
    )

    direct = resolve_direct_approval(
        DirectApprovalRequest(
            selector=selector,
            kind=cast(DirectApprovalKind | None, kind),
            kind_explicit=kind is not None,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            wait=wait,
            project=project,
            cwd=Path.cwd(),
        )
    )
    if direct is None:
        assert isinstance(outcome, PendingPlanMiss)
        render_miss(outcome, pending_plans())
        raise _rendered_error(miss_error_code(outcome), selector, outcome.header)
    if isinstance(direct, DirectApprovalRefusal):
        raise DirectApprovalRefused(direct)
    if direct.recovery is not None:
        if dry_run:
            from sase.main.plan_approve_render import render_coder_recovery_dry_run

            render_coder_recovery_dry_run(direct)
            return None
        from sase.main.plan_approve_render import render_coder_recovery
        from sase.main.plan_direct_approval_run import execute_coder_recovery

        recovery_result = execute_coder_recovery(direct)
        render_coder_recovery(recovery_result)
        return recovery_result
    if dry_run:
        from sase.main.plan_approve_render import render_direct_approval_dry_run

        render_direct_approval_dry_run(direct)
        return None
    from sase.main.plan_approve_render import render_direct_approval
    from sase.main.plan_direct_approval_run import execute_direct_approval

    result = execute_direct_approval(direct)
    render_direct_approval(result)
    return result


def _approve_pending_plan(
    plan: PendingPlan,
    *,
    selector: str | None,
    kind: str | None,
    coder_prompt: str | None,
    coder_model: str | None,
    wait: str | None,
    dry_run: bool,
    project: str | None,
) -> PlanApprovalActionResult | None:
    """Run or preview the existing gate response path."""
    if project:
        raise PlanApprovalActionError(
            "invalid_request",
            "project",
            "-P/--project only applies to plans without a live approval gate",
        )
    if plan.tier == "epic" and kind is None:
        from sase.main.plan_direct_approval import (
            DirectApprovalRefusal,
            DirectApprovalRefused,
        )

        displayed = selector or plan.display_name
        raise DirectApprovalRefused(
            DirectApprovalRefusal(
                code="epic_guard",
                header=f"✗ {plan.display_name} is an epic plan",
                detail_lines=(
                    f"Approve it as an epic:        sase plan approve {displayed} -k epic",
                    f"Or run it as a single tale:   sase plan approve {displayed} -k tale",
                ),
            )
        )
    selected_kind = kind or "tale"
    notification = plan.notification
    ensure_plan_notification_available(notification)
    if dry_run:
        from sase.main.plan_approve_render import render_gate_approval_dry_run
        from sase._plan_approval_protocol import resolve_plan_approval_choice

        resolve_plan_approval_choice(notification.files[0], selected_kind)
        render_gate_approval_dry_run(plan, selected_kind)
        return None
    result = execute_plan_approval_response(
        plan_context_from_notification(notification),
        selected_kind,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
        wait=wait,
        epic_launch_mode="launch",
        epic_launch_origin="cli",
    )
    from sase.main.plan_approve_render import render_gate_approval

    render_gate_approval(plan, result)
    return result


def _render_omitted_direct_approval_miss(outcome: PendingPlanMiss) -> None:
    """Explain the new explicit-file route when no live proposal is selected."""
    from rich.console import Console

    out = Console(stderr=True)
    out.print("[red]✗ Nothing is awaiting approval.[/red]")
    out.print("  To approve a plan without a live gate, pass its name or file:")
    out.print("    sase plan approve <PLAN>")
    if outcome.detail_lines:
        out.print(f"  [dim]{outcome.detail_lines[0]}[/dim]")


def resolve_plan_for_cli(selector: str | None) -> PendingPlan:
    """Resolve PLAN through the structured selector, rendering misses."""
    from sase.main.plan_pending import PendingPlanAmbiguity, PendingPlanMiss

    outcome = resolve_pending_plan_selector(selector)
    if isinstance(outcome, PendingPlanAmbiguity):
        render_ambiguity(outcome, pending_plans())
        raise _rendered_error(
            "ambiguous_prefix", outcome.selector, "action prefix is ambiguous"
        )
    if isinstance(outcome, PendingPlanMiss):
        render_miss(outcome, pending_plans())
        code = (
            "missing_selector" if outcome.selector is None else miss_error_code(outcome)
        )
        raise _rendered_error(code, outcome.selector or "selector", outcome.header)
    return outcome.plan


class _RenderedSelectionError(PlanApprovalActionError):
    """A selection error already rendered by the shared renderer."""

    _sase_rendered = True


def _rendered_error(code: str, target: str, message: str) -> PlanApprovalActionError:
    """Build a selection error already rendered by the shared renderer."""
    return _RenderedSelectionError(code, target, message)


def _validate_wait_spec_for_cli(wait: str | None) -> None:
    """Validate ``sase plan approve --wait`` before resolving the proposal."""
    text = wait.strip() if isinstance(wait, str) else None
    if not text:
        return
    from sase.wait_spec import WaitSpecError, parse_wait_spec

    try:
        parse_wait_spec(text)
    except WaitSpecError as exc:
        raise PlanApprovalActionError("invalid_request", "wait", str(exc)) from exc


def is_auto_approve_active() -> bool:
    """Check if auto-approve is active via env var or agent_meta.json.

    Returns True if SASE_AGENT_AUTO_APPROVE env var is set, or if the
    ``approve`` field is truthy in the agent's ``agent_meta.json`` (located
    via SASE_ARTIFACTS_DIR).
    """
    _argument, has_argument = _raw_auto_plan_argument()
    return bool(
        has_argument
        or os.environ.get("SASE_AGENT_AUTO_APPROVE")
        or _read_agent_meta().get("approve")
    )


def get_tmux_prefix() -> str:
    """Get the tmux window prefix for notifications."""
    project_dir = provider_project_dir_from_env() or "."
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
