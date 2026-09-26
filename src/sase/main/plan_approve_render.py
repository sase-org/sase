"""Human output for the two ``sase plan approve`` routes."""

from __future__ import annotations

import shlex
import sys
from typing import TYPE_CHECKING

from sase.core.term_color import should_colorize

if TYPE_CHECKING:
    from rich.console import Console
    from sase.main.plan_direct_approval import DirectApprovalPlan, DirectApprovalRefusal
    from sase.main.plan_direct_approval_run import DirectApprovalOutcome
    from sase.main.plan_pending import PendingPlan
    from sase.plan_approval_actions import PlanApprovalActionResult


def _print_recovery_command(out: Console, prompt: str) -> None:
    """Print a copy-pasteable ``sase run`` for *prompt*, unwrapped and unstyled."""
    from rich.markup import escape

    out.print(f"    sase run {escape(shlex.quote(prompt))}", soft_wrap=True)


def _console(*, stderr: bool) -> Console:
    from rich.console import Console

    stream = sys.stderr if stderr else sys.stdout
    color = should_colorize(stream)
    return Console(
        stderr=stderr, highlight=False, force_terminal=color, no_color=not color
    )


def render_gate_approval(plan: PendingPlan, result: PlanApprovalActionResult) -> None:
    """Render a completed live-gate approval as an approval card."""
    out = _console(stderr=False)
    out.print(
        f"[green]✓ {result.message}[/green] · [bold cyan]{plan.display_name}[/bold cyan]"
    )
    if plan.title:
        out.print(f"  {plan.title}")
    if result.coder_agent:
        shell = result.gate_shell_member or "gate shell"
        out.print(
            f"  [dim]coder[/dim]   [bold]{result.coder_agent}[/bold] · launched by {shell}"
        )
        out.print(f"\n  [dim]follow[/dim]  sase agent show {result.coder_agent}")
    elif result.coder_error:
        out.print(f"  [yellow]! coder launch failed:[/yellow] {result.coder_error}")
    elif result.epic_launch_monitor_id is not None:
        out.print(
            f"  [dim]launch[/dim]  monitor {result.epic_launch_monitor_id} · "
            f"sase monitor show {result.epic_launch_monitor_id} --follow"
        )
    elif result.epic_launch_task_id is not None:
        out.print(
            f"  [dim]launch[/dim]  proc {result.epic_launch_task_id} · "
            f"sase proc show {result.epic_launch_task_id} --follow"
        )
    else:
        out.print("  [dim]coder[/dim]   the gate shell launches it next")
    out.print(
        f"  [dim]gate[/dim]    {result.notification_id[:8]} → {result.response_path}"
    )


def render_gate_approval_dry_run(plan: PendingPlan, kind: str) -> None:
    """Render a read-only preview of a live-gate approval."""
    out = _console(stderr=False)
    out.print(
        f"[cyan]◇ Dry run[/cyan] · [bold cyan]{plan.display_name}[/bold cyan] "
        f"would be approved as a {kind}"
    )
    if plan.title:
        out.print(f"  {plan.title}")
    out.print(
        f"  [dim]gate[/dim]    {plan.notification.id[:8]} · the gate shell launches the coder"
    )
    out.print(
        "\n  [dim]Nothing was changed. Re-run without -n/--dry-run to approve.[/dim]"
    )


def render_direct_approval(outcome: DirectApprovalOutcome) -> None:
    """Render a direct approval, including a coder this command did not launch."""
    plan = outcome.plan
    out = _console(stderr=False)
    if outcome.coder_error or outcome.gate_answered_concurrently:
        out.print(
            f"[green]✓ Plan committed[/green] · [bold cyan]{plan.name}[/bold cyan]"
            f" · {outcome.plan_ref}"
        )
    else:
        out.print(
            f"[green]✓ {plan.kind.title()} approved[/green] · [bold cyan]{plan.name}[/bold cyan]"
        )
    if plan.title:
        out.print(f"  {plan.title}")
    plan_line = outcome.plan_ref or str(outcome.local_plan_path)
    if outcome.saved_plan_path:
        plan_line += " · committed to sase"
    out.print(f"\n  [dim]plan[/dim]    {plan_line}")
    if plan.kind == "commit":
        out.print("  [dim]coder[/dim]   none · commit only")
    elif outcome.gate_answered_concurrently:
        out.print("  [dim]coder[/dim]   none launched · left to the gate's responder")
    elif outcome.coder is not None:
        route = (
            "agent session " + str(plan.placement.agent_session)
            if plan.placement.mode == "session"
            else "standalone"
        )
        name = outcome.coder.agent_name
        label = name or f"PID {outcome.coder.pid}"
        out.print(
            f"  [dim]coder[/dim]   [bold]{label}[/bold] · {route}"
            f" · %model:{plan.model_directive or 'custom'}"
        )
    else:
        route = "session" if plan.placement.mode == "session" else "standalone"
        out.print(
            f"  [dim]coder[/dim]   {route} · %model:{plan.model_directive or 'custom'}"
        )
    if (
        plan.placement.mode == "standalone"
        and plan.placement.reason
        and not outcome.gate_answered_concurrently
    ):
        out.print(f"          [dim]no agent session: {plan.placement.reason}[/dim]")
    if plan.gate is None:
        out.print("  [dim]gate[/dim]    none · never proposed")
    elif outcome.gate_answered_concurrently:
        out.print(
            f"  [dim]gate[/dim]    {plan.gate.notification_id[:8]} · answered concurrently, not closed here"
        )
    else:
        out.print(
            f"  [dim]gate[/dim]    {plan.gate.notification_id[:8]} · {plan.gate.state} approval gate closed"
        )
    for warning in outcome.warnings:
        out.print(f"  [yellow]! {warning}[/yellow]")
    if outcome.coder_error:
        out.print(f"\n[red]✗ Coder launch failed:[/red] {outcome.coder_error}")
        out.print("  Launch it yourself:")
        _print_recovery_command(out, outcome.coder_prompt)
    elif outcome.incomplete:
        out.print("\n  Check whether the gate's responder launched a coder:")
        out.print("    sase agent list")
        out.print("  If it did not, launch it yourself:")
        _print_recovery_command(out, outcome.coder_prompt)
    elif outcome.coder is not None:
        follow = (
            f"sase agent show {outcome.coder.agent_name}"
            if outcome.coder.agent_name
            else "sase agent list"
        )
        out.print(f"\n  [dim]follow[/dim]  {follow}")


def render_direct_approval_dry_run(plan: DirectApprovalPlan) -> None:
    """Render the direct-route preview without mutating anything."""
    out = _console(stderr=False)
    out.print(
        f"[cyan]◇ Dry run[/cyan] · [bold cyan]{plan.name}[/bold cyan] would be approved as a {plan.kind}"
    )
    if plan.title:
        out.print(f"  {plan.title}")
    out.print(f"\n  [dim]plan[/dim]    {plan.source_path}")
    if plan.predicted_plan_ref:
        out.print(f"          → {plan.predicted_plan_ref} in sase")
    route = (
        "agent session " + str(plan.placement.agent_session)
        if plan.placement.mode == "session"
        else "standalone"
    )
    out.print(
        f"  [dim]coder[/dim]   {route} · %model:{plan.model_directive or 'custom'}"
    )
    if plan.placement.mode == "standalone" and plan.placement.reason:
        out.print(f"          [dim]no agent session: {plan.placement.reason}[/dim]")
    out.print(
        "  [dim]gate[/dim]    none · never proposed"
        if plan.gate is None
        else f"  [dim]gate[/dim]    {plan.gate.notification_id[:8]} · {plan.gate.state}"
    )
    out.print(f"  [dim]prompt[/dim]  {plan.coder_prompt_preview}")
    out.print(
        "\n  [dim]Nothing was changed. Re-run without -n/--dry-run to approve.[/dim]"
    )


def render_direct_approval_refusal(refusal: DirectApprovalRefusal) -> None:
    """Render a deliberate direct-route refusal to stderr."""
    out = _console(stderr=True)
    header = refusal.header if refusal.header.startswith("✗") else f"✗ {refusal.header}"
    out.print(f"[red]{header}[/red]")
    for line in refusal.detail_lines:
        out.print(f"  {line}")
    for hint in refusal.hints:
        if not any(hint in line for line in refusal.detail_lines):
            out.print(f"  [dim]{hint}[/dim]")


def render_coder_recovery(outcome: DirectApprovalOutcome) -> None:
    """Render a relaunched replacement coder as a recovery card."""
    plan = outcome.plan
    recovery = plan.recovery
    out = _console(stderr=False)
    out.print(f"[green]↻ Coder relaunched[/green] · [bold cyan]{plan.name}[/bold cyan]")
    if plan.title:
        out.print(f"  {plan.title}")
    out.print(f"\n  [dim]plan[/dim]    {_recovery_plan_line(recovery, plan)}")
    out.print(f"  [dim]before[/dim]  {_recovery_before_line(recovery)}")
    if plan.kind == "commit":
        out.print("  [dim]coder[/dim]   none · commit only")
    elif outcome.coder is not None:
        route = (
            "agent session " + str(plan.placement.agent_session)
            if plan.placement.mode == "session"
            else "standalone"
        )
        name = outcome.coder.agent_name
        label = name or f"PID {outcome.coder.pid}"
        out.print(
            f"  [dim]coder[/dim]   [bold]{label}[/bold] · {route}"
            f" · %model:{plan.model_directive or 'custom'}"
        )
    else:
        route = "session" if plan.placement.mode == "session" else "standalone"
        out.print(
            f"  [dim]coder[/dim]   {route} · %model:{plan.model_directive or 'custom'}"
        )
    if (
        plan.placement.mode == "standalone"
        and plan.placement.reason
        and outcome.coder is not None
    ):
        out.print(f"          [dim]no agent session: {plan.placement.reason}[/dim]")
    for warning in outcome.warnings:
        out.print(f"  [yellow]! {warning}[/yellow]")
    if outcome.coder_error:
        out.print(f"\n[red]✗ Coder launch failed:[/red] {outcome.coder_error}")
        out.print("  Launch it yourself:")
        _print_recovery_command(out, outcome.coder_prompt)
    elif outcome.coder is not None:
        follow = (
            f"sase agent show {outcome.coder.agent_name}"
            if outcome.coder.agent_name
            else "sase agent list"
        )
        out.print(f"\n  [dim]follow[/dim]  {follow}")


def render_coder_recovery_dry_run(plan: DirectApprovalPlan) -> None:
    """Render a read-only preview of a coder recovery."""
    out = _console(stderr=False)
    out.print(
        f"[cyan]◇ Dry run[/cyan] · [bold cyan]{plan.name}[/bold cyan] "
        "would get a replacement coder"
    )
    if plan.title:
        out.print(f"  {plan.title}")
    out.print(f"\n  [dim]plan[/dim]    {_recovery_plan_line(plan.recovery, plan)}")
    out.print(f"  [dim]before[/dim]  {_recovery_before_line(plan.recovery)}")
    route = (
        "agent session " + str(plan.placement.agent_session)
        if plan.placement.mode == "session"
        else "standalone"
    )
    out.print(
        f"  [dim]coder[/dim]   {route} · %model:{plan.model_directive or 'custom'}"
    )
    if plan.placement.mode == "standalone" and plan.placement.reason:
        out.print(f"          [dim]no agent session: {plan.placement.reason}[/dim]")
    out.print(f"  [dim]prompt[/dim]  {plan.coder_prompt_preview}")
    out.print(
        "\n  [dim]Nothing was changed. Re-run without -n/--dry-run to approve.[/dim]"
    )


def _recovery_plan_line(recovery: object, plan: DirectApprovalPlan) -> str:
    from sase.main.plan_direct_approval_recovery import CoderRecovery

    if not isinstance(recovery, CoderRecovery):
        return plan.predicted_plan_ref or str(plan.source_path)
    age = f" {recovery.approved_age}" if recovery.approved_age else ""
    line = f"{recovery.plan_argument} · approved as a {recovery.approved_action}{age}"
    if recovery.gate_id:
        line += f" · gate {recovery.gate_id}"
    return line


def _recovery_before_line(recovery: object) -> str:
    from sase.main.plan_direct_approval_recovery import (
        CoderRecovery,
        prior_coder_word,
    )

    if not isinstance(recovery, CoderRecovery) or not recovery.prior_coders:
        return "none found · the approval's coder never launched"
    prior = recovery.prior_coders[0]
    return f"{prior.name} · {prior_coder_word(prior)}"


def render_approval_error(error: Exception) -> None:
    """Render action failures with the recovery hint appropriate to their code."""
    out = _console(stderr=True)
    code = getattr(error, "code", "")
    out.print(f"[red]✗ {error}[/red]")
    if code == "git_credential_denied":
        out.print("  [dim]Check git credentials, then re-run the approval.[/dim]")
    elif code == "plan_archive_failed":
        out.print(
            "  [dim]Nothing was approved; fix the archive failure and re-run.[/dim]"
        )
    elif code in {
        "conflict_already_handled",
        "not_found",
        "already_committed",
        "already_approved",
    }:
        out.print("  [dim]Run `sase plan list` to inspect plan state.[/dim]")


__all__ = [
    "render_approval_error",
    "render_coder_recovery",
    "render_coder_recovery_dry_run",
    "render_direct_approval",
    "render_direct_approval_dry_run",
    "render_direct_approval_refusal",
    "render_gate_approval",
    "render_gate_approval_dry_run",
]
