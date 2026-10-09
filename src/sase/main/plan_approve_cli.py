"""``sase plan approve`` command entry and selector routing.

Routes a selector to a live gate or a file-backed direct approval, then
reports the outcome through the shared renderers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NoReturn, cast

from sase.main._plan_approve_shared import rendered_error
from sase.main.plan_approve_pending import approve_pending_plan
from sase.main.plan_direct_approval import DirectApprovalKind
from sase.main.plan_pending import (
    PendingPlanAmbiguity,
    PendingPlanMatch,
    PendingPlanMiss,
    pending_plans,
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
)

__all__ = ["handle_plan_approve_command"]


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
            decide=tuple(getattr(args, "decide", None) or ()),
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
        from sase.main.plan_decide import DecideError

        if isinstance(exc, DecideError):
            from sase.main.plan_approve_render import render_decide_error

            render_decide_error(exc)
            sys.exit(2)
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
    decide: tuple[str, ...] = (),
) -> PlanApprovalActionResult | object | None:
    """Route a selector to a live gate or a file-backed direct approval."""
    _validate_wait_spec_for_cli(wait)
    outcome = resolve_pending_plan_selector(selector)
    if isinstance(outcome, PendingPlanMatch):
        return approve_pending_plan(
            outcome.plan,
            selector=selector,
            kind=kind,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            wait=wait,
            dry_run=dry_run,
            project=project,
            decide=decide,
        )
    if isinstance(outcome, PendingPlanAmbiguity):
        render_ambiguity(outcome, pending_plans())
        raise rendered_error(
            "ambiguous_prefix", outcome.selector, "action prefix is ambiguous"
        )
    if selector is None or not selector.strip():
        _render_omitted_direct_approval_miss(outcome)
        raise rendered_error("missing_selector", "selector", outcome.header)

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
            decide=tuple(decide or ()),
        )
    )
    if direct is None:
        assert isinstance(outcome, PendingPlanMiss)
        render_miss(outcome, pending_plans())
        raise rendered_error(miss_error_code(outcome), selector, outcome.header)
    if isinstance(direct, DirectApprovalRefusal):
        raise DirectApprovalRefused(direct)
    from sase.main.plan_decide import direct_card_lines, retry_line_for_plan

    if direct.recovery is not None:
        if dry_run:
            from sase.main.plan_approve_render import render_coder_recovery_dry_run

            render_coder_recovery_dry_run(
                direct,
                retry_line=retry_line_for_plan(direct.source_path),
            )
            return None
        from sase.main.plan_approve_render import render_coder_recovery
        from sase.main.plan_direct_approval_run import execute_coder_recovery

        recovery_result = execute_coder_recovery(direct)
        render_coder_recovery(
            recovery_result,
            retry_line=retry_line_for_plan(recovery_result.local_plan_path),
        )
        return recovery_result
    if dry_run:
        from sase.main.plan_approve_render import render_direct_approval_dry_run

        render_direct_approval_dry_run(
            direct, decision_lines=direct_card_lines(direct, dry_run=True)
        )
        return None
    from sase.main.plan_approve_render import render_direct_approval
    from sase.main.plan_direct_approval_run import execute_direct_approval

    result = execute_direct_approval(direct)
    render_direct_approval(
        result, decision_lines=direct_card_lines(direct, dry_run=False)
    )
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
