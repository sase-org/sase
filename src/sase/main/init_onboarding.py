"""Bare ``sase init`` onboarding coordinator."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import copy
from pathlib import Path
import sys
from typing import TextIO

from rich.console import Console

from .init_plan import InitAction, InitPlan
from .init_registry import InitCommandSpec, iter_init_command_specs


def _console_for(file: TextIO) -> Console:
    is_tty = file.isatty()
    return Console(
        file=file,
        force_terminal=is_tty,
        color_system="auto" if is_tty else None,
        no_color=not is_tty,
        soft_wrap=True,
    )


def _fallback_summary(plan: InitPlan) -> str:
    if plan.summary:
        return plan.summary
    count = len(plan.actions)
    if count == 1:
        action = plan.actions[0]
        detail = f" {action.detail}" if action.detail else ""
        return f"{action.operation} {action.path}{detail}"
    return f"{count} actions"


def _render_row(prefix: str, plan: InitPlan) -> str:
    return f"  {prefix:<3} init {plan.command:<6} {_fallback_summary(plan)}"


def _render_plans(console: Console, plans: Sequence[InitPlan]) -> None:
    console.print("SASE initialization check", style="bold")

    up_to_date = [plan for plan in plans if not plan.has_changes and plan.runnable]
    changed = [plan for plan in plans if plan.has_changes]
    warnings = [(plan, warning) for plan in plans for warning in plan.warnings]
    blockers = [(plan, blocker) for plan in plans for blocker in plan.blockers]

    if up_to_date:
        console.print()
        console.print("Up to date:", style="dim")
        for plan in up_to_date:
            console.print(_render_row("ok", plan), style="dim")

    if changed:
        console.print()
        console.print("Needs attention:", style="bold")
        for plan in changed:
            prefix = "run" if plan.runnable else "hold"
            console.print(_render_row(prefix, plan))

    if warnings:
        console.print()
        console.print("Warnings:", style="yellow")
        for plan, warning in warnings:
            console.print(f"  init {plan.command}: {warning}")

    if blockers:
        console.print()
        console.print("Blockers:", style="red")
        for plan, blocker in blockers:
            console.print(f"  init {plan.command}: {blocker}")


def _render_noop(console: Console, specs: Sequence[InitCommandSpec]) -> None:
    checked = ", ".join(spec.name for spec in specs)
    console.print("SASE is initialized. No init subcommands need to run.")
    console.print(f"Checked: {checked}.")


def _render_no_specs(console: Console) -> None:
    console.print("SASE initialization check", style="bold")
    console.print()
    console.print("No init planners are registered yet.")
    console.print("Run an explicit subcommand: init memory, init sdd, or init skills.")


def _prompt_for_plan(
    plan: InitPlan,
    *,
    input_func: Callable[[str], str],
) -> bool:
    command = f"sase init {plan.command}"
    if plan.command == "skills":
        command = f"{command} --force"
    prompt = f"Run `{command}` now?"
    if plan.command == "memory":
        prompt += " This may commit and push generated project memory changes."
    answer = input_func(f"{prompt} [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


def _apply_args(args: argparse.Namespace, spec: InitCommandSpec) -> argparse.Namespace:
    apply_args = copy.copy(args)
    apply_args.init_subcommand = spec.name
    if spec.name == "skills":
        apply_args.force = True
    return apply_args


def _plan_specs(
    args: argparse.Namespace,
    specs: Sequence[InitCommandSpec],
) -> tuple[InitPlan, ...]:
    return tuple(spec.plan(args) for spec in specs)


def run_init_onboarding(
    args: argparse.Namespace,
    *,
    specs: Sequence[InitCommandSpec] | None = None,
    input_func: Callable[[str], str] = input,
    stdin: TextIO | None = None,
    console: Console | None = None,
) -> int:
    """Run bare ``sase init`` and return a process exit code."""
    active_specs = tuple(iter_init_command_specs() if specs is None else specs)
    out_console = console or _console_for(sys.stdout)
    is_tty = (stdin or sys.stdin).isatty()

    if not active_specs:
        _render_no_specs(out_console)
        return 1

    plans = _plan_specs(args, active_specs)
    has_changes = any(plan.has_changes for plan in plans)
    has_blockers = any(not plan.runnable for plan in plans)

    if not has_changes and not has_blockers:
        _render_noop(out_console, active_specs)
        return 0

    _render_plans(out_console, plans)

    if has_blockers:
        return 1

    if getattr(args, "check", False):
        return 1

    if not getattr(args, "yes", False) and not is_tty:
        out_console.print()
        out_console.print("Run `sase init --yes` to apply these changes.")
        return 1

    spec_by_name = {spec.name: spec for spec in active_specs}
    for plan in plans:
        if not plan.has_changes or not plan.runnable:
            continue
        spec = spec_by_name[plan.command]
        should_run = getattr(args, "yes", False) or _prompt_for_plan(
            plan, input_func=input_func
        )
        if not should_run:
            continue
        exit_code = spec.run(_apply_args(args, spec))
        if exit_code != 0:
            return exit_code

    return 0


__all__ = [
    "InitAction",
    "InitPlan",
    "run_init_onboarding",
]
