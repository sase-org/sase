"""``sase agent drain`` — relaunch agents stranded by a disabled provider."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import sys
from typing import Any

from rich.console import Console
from rich.text import Text

from sase.agent.provider_drain import (
    ProviderDrainError,
    ProviderDrainOutcome,
    ProviderDrainPlan,
    execute_provider_drain,
    plan_provider_drain,
)
from sase.agents._drain_render import (
    envelope_from_error,
    envelope_from_plan,
    print_json,
    print_planning_error,
    print_step,
    render_preview_panel,
    render_receipt_panel,
)

PlanFn = Callable[..., ProviderDrainPlan]
ExecuteFn = Callable[..., ProviderDrainOutcome]
ConfirmFn = Callable[[ProviderDrainPlan, Console], bool]
IsTtyFn = Callable[[], bool]
ReportFn = Callable[["_AgentDrainCommandResult | None"], None]

_LIVE_CONFIRM_STATUSES = frozenset({"STARTING", "RUNNING", "WAITING"})


@dataclass(frozen=True)
class _AgentDrainCommandResult:
    """Exit status and durable-operation payload for one drain command run."""

    exit_code: int
    success: bool
    message: str
    payload: Mapping[str, Any]


def run_agents_drain(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    plan_fn: PlanFn = plan_provider_drain,
    execute_fn: ExecuteFn = execute_provider_drain,
    confirm_fn: ConfirmFn | None = None,
    is_tty_fn: IsTtyFn | None = None,
    report_fn: ReportFn | None = None,
) -> _AgentDrainCommandResult:
    """Plan, optionally confirm, execute, render, and summarize a provider drain.

    *report_fn*, when given, always runs from a ``finally`` block with the
    final result (``None`` only if planning or execution raised something
    other than :class:`ProviderDrainError`) -- this is the seam an automatic
    usage-limit drain uses to send its one enriched notification even when
    the drain itself fails partway through.
    """
    result: _AgentDrainCommandResult | None = None
    try:
        result = _run_agents_drain(
            args,
            console=console,
            err_console=err_console,
            plan_fn=plan_fn,
            execute_fn=execute_fn,
            confirm_fn=confirm_fn,
            is_tty_fn=is_tty_fn,
        )
        return result
    finally:
        if report_fn is not None:
            report_fn(result)


def _run_agents_drain(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    plan_fn: PlanFn = plan_provider_drain,
    execute_fn: ExecuteFn = execute_provider_drain,
    confirm_fn: ConfirmFn | None = None,
    is_tty_fn: IsTtyFn | None = None,
) -> _AgentDrainCommandResult:
    """Plan, optionally confirm, execute, render, and summarize a provider drain."""
    provider = str(args.provider)
    as_json = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))
    assume_yes = bool(getattr(args, "yes", False))
    limit = int(getattr(args, "limit", 20))
    model = getattr(args, "model", None)
    out = console or Console()
    err = err_console or Console(stderr=True)
    confirm = confirm_fn or _confirm_interactively
    is_tty = is_tty_fn or _stdin_is_tty

    if limit < 0:
        error = ProviderDrainError(
            reason="invalid_limit",
            message="--limit must be zero or greater.",
            hint="Use --limit 0 to move no agents but still report candidates.",
        )
        return _planning_error(
            provider,
            error,
            as_json=as_json,
            dry_run=dry_run,
            limit=limit,
            model=model,
            err=err,
        )

    try:
        plan = plan_fn(provider, model_override=model, limit=limit)
    except ProviderDrainError as drain_error:
        return _planning_error(
            provider,
            drain_error,
            as_json=as_json,
            dry_run=dry_run,
            limit=limit,
            model=model,
            err=err,
        )

    if dry_run:
        payload = envelope_from_plan(plan, dry_run=True)
        if as_json:
            print_json(payload)
        else:
            out.print(render_preview_panel(plan))
        return _AgentDrainCommandResult(
            exit_code=0,
            success=True,
            message=_summary_message(plan),
            payload=payload,
        )

    if not plan.moves:
        error_payload = {
            "reason": "nothing_to_drain",
            "message": "No agents can be relaunched for this disabled provider.",
        }
        payload = envelope_from_plan(plan, dry_run=False, error=error_payload)
        if as_json:
            print_json(payload)
        else:
            out.print(render_preview_panel(plan))
            err.print(Text(error_payload["message"], style="yellow"))
        return _AgentDrainCommandResult(
            exit_code=2,
            success=False,
            message=error_payload["message"],
            payload=payload,
        )

    if _needs_confirmation(plan) and not assume_yes and not as_json:
        if not is_tty():
            message = (
                "Drain needs confirmation because live in-flight work will be "
                "discarded; pass -y to run non-interactively."
            )
            err.print(Text(message, style="bold red"))
            payload = envelope_from_plan(
                plan,
                dry_run=False,
                error={"reason": "confirmation_required", "message": message},
            )
            return _AgentDrainCommandResult(
                exit_code=2,
                success=False,
                message=message,
                payload=payload,
            )
        if not confirm(plan, out):
            message = "Drain cancelled; nothing was changed."
            err.print(Text(message, style="yellow"))
            payload = envelope_from_plan(
                plan,
                dry_run=False,
                error={"reason": "declined", "message": message},
            )
            return _AgentDrainCommandResult(
                exit_code=2,
                success=False,
                message=message,
                payload=payload,
            )
    elif not as_json:
        out.print(render_preview_panel(plan))
        _print_discard_note(out, plan)

    def _progress(step: str, status: str, detail: str) -> None:
        if not as_json:
            print_step(out, step, status, detail)

    outcome = execute_fn(plan, progress=_progress)
    failed = outcome.failed
    execution_error: dict[str, str] | None = (
        {"reason": "move_failed", "message": f"{failed} drain move(s) failed."}
        if failed
        else None
    )
    payload = envelope_from_plan(
        plan,
        dry_run=False,
        outcome=outcome,
        error=execution_error,
    )
    if as_json:
        print_json(payload)
    else:
        out.print(render_receipt_panel(plan, outcome))
    message = _summary_message(plan, outcome=outcome)
    return _AgentDrainCommandResult(
        exit_code=1 if failed else 0,
        success=failed == 0,
        message=message,
        payload=payload,
    )


def _planning_error(
    provider: str,
    error: ProviderDrainError,
    *,
    as_json: bool,
    dry_run: bool,
    limit: int,
    model: str | None,
    err: Console,
) -> _AgentDrainCommandResult:
    payload = envelope_from_error(
        provider=provider,
        error=error,
        dry_run=dry_run,
        limit=limit,
        model_override=model,
    )
    if as_json:
        print_json(payload)
    else:
        print_planning_error(err, error)
    return _AgentDrainCommandResult(
        exit_code=2,
        success=False,
        message=error.message,
        payload=payload,
    )


def _needs_confirmation(plan: ProviderDrainPlan) -> bool:
    return any(move.status in _LIVE_CONFIRM_STATUSES for move in plan.moves)


def _print_discard_note(console: Console, plan: ProviderDrainPlan) -> None:
    if _needs_confirmation(plan):
        console.print(
            Text(
                "Draining live agents discards their in-flight work; chat "
                "transcripts are kept.",
                style="yellow",
            )
        )


def _summary_message(
    plan: ProviderDrainPlan,
    *,
    outcome: ProviderDrainOutcome | None = None,
) -> str:
    relaunched = 0 if outcome is None else outcome.relaunched
    failed = 0 if outcome is None else outcome.failed
    if outcome is None:
        return (
            f"Planned drain for {plan.provider}: {len(plan.moves)} move(s), "
            f"{len(plan.skips)} left alone"
        )
    return (
        f"Drained {plan.provider}: {relaunched} relaunched, "
        f"{len(plan.skips)} left alone, {failed} failed"
    )


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _confirm_interactively(plan: ProviderDrainPlan, out: Console) -> bool:
    out.print(render_preview_panel(plan))
    _print_discard_note(out, plan)
    try:
        answer = out.input(f"Drain provider '{plan.provider}'? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}
