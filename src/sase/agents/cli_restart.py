"""``sase agent restart`` — stop a named agent and relaunch its stored prompt."""

from __future__ import annotations

import argparse
import difflib
import sys
from collections.abc import Callable

from rich.console import Console
from rich.text import Text

from sase.agent.restart import (
    AgentRestartError,
    AgentRestartOutcome,
    AgentRestartPlan,
    execute_agent_restart,
    plan_agent_restart,
)
from sase.agents._restart_render import (
    envelope_from_error,
    envelope_from_plan,
    print_json,
    print_kill_failure,
    print_partial_failure,
    print_planning_error,
    print_preview_warnings,
    print_step,
    render_preview_panel,
    render_receipt_panel,
)

PlanFn = Callable[..., AgentRestartPlan]
ExecuteFn = Callable[..., AgentRestartOutcome]
ConfirmFn = Callable[[AgentRestartPlan, Console], bool]
IsTtyFn = Callable[[], bool]


def handle_agents_restart(
    args: argparse.Namespace,
    *,
    console: Console | None = None,
    err_console: Console | None = None,
    plan_fn: PlanFn = plan_agent_restart,
    execute_fn: ExecuteFn = execute_agent_restart,
    confirm_fn: ConfirmFn | None = None,
    is_tty_fn: IsTtyFn | None = None,
) -> int:
    """Preview, confirm, and run a named-agent restart."""
    name: str = args.name
    as_json = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))
    assume_yes = bool(getattr(args, "yes", False))
    model = getattr(args, "model", None)
    out = console or Console()
    err = err_console or Console(stderr=True)
    confirm = confirm_fn or _confirm_interactively
    is_tty = is_tty_fn or _stdin_is_tty

    try:
        plan = plan_fn(name, model_override=model)
    except AgentRestartError as error:
        return _planning_error(name, error, as_json=as_json, dry_run=dry_run, err=err)

    if dry_run:
        if as_json:
            print_json(envelope_from_plan(plan, dry_run=True))
        else:
            out.print(render_preview_panel(plan))
            print_preview_warnings(out, plan.preview)
        return 0

    if plan.preview.is_live and not assume_yes and is_tty() and not as_json:
        if not confirm(plan, out):
            if as_json:
                print_json(
                    envelope_from_plan(
                        plan,
                        dry_run=False,
                        error={
                            "reason": "declined",
                            "message": "Restart cancelled; nothing was changed.",
                        },
                    )
                )
            else:
                err.print(
                    Text("Restart cancelled; nothing was changed.", style="yellow")
                )
            return 2
    elif not as_json:
        out.print(render_preview_panel(plan))
        print_preview_warnings(out, plan.preview)

    def _progress(step: str, status: str, detail: str) -> None:
        if not as_json:
            print_step(out, step, status, detail)

    outcome = execute_fn(plan, progress=_progress)
    if outcome.status == "kill_failed":
        if as_json:
            print_json(
                envelope_from_plan(
                    plan,
                    dry_run=False,
                    outcome=outcome,
                    error={
                        "reason": "kill_failed",
                        "message": outcome.error or outcome.stop_result.message,
                    },
                )
            )
        else:
            print_kill_failure(err, outcome)
        return 2
    if outcome.status == "partial":
        if as_json:
            print_json(
                envelope_from_plan(
                    plan,
                    dry_run=False,
                    outcome=outcome,
                    error={
                        "reason": "partial",
                        "message": outcome.error or "Relaunch failed.",
                    },
                )
            )
        else:
            print_partial_failure(err, outcome)
        return 1

    if as_json:
        print_json(envelope_from_plan(plan, dry_run=False, outcome=outcome))
    else:
        out.print(render_receipt_panel(plan, outcome))
    return 0


def _planning_error(
    name: str,
    error: AgentRestartError,
    *,
    as_json: bool,
    dry_run: bool,
    err: Console,
) -> int:
    suggestions: list[str] = []
    if error.reason == "not_found":
        suggestions = _near_miss_names(name)
    if as_json:
        payload = envelope_from_error(name=name, error=error, dry_run=dry_run)
        if suggestions:
            payload["suggestions"] = suggestions
        print_json(payload)
    else:
        print_planning_error(err, error, suggestions=suggestions)
    return 2


def _near_miss_names(name: str) -> list[str]:
    from sase.agent.running import list_running_agents

    names = [agent.name for agent in list_running_agents() if agent.name]
    return difflib.get_close_matches(name, names, n=3)


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _confirm_interactively(plan: AgentRestartPlan, out: Console) -> bool:
    out.print(render_preview_panel(plan))
    print_preview_warnings(out, plan.preview)
    try:
        answer = out.input(f"Restart agent '{plan.presented_name}'? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}
