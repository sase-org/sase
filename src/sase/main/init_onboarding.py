"""Bare ``sase init`` onboarding coordinator."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import copy
from pathlib import Path
import sys
from typing import TextIO

from rich.console import Console

from ._init_chezmoi_deploy import defer_chezmoi_deploy, deploy_deferred_chezmoi
from .init_plan import InitAction, InitPlan
from .init_project_scope import is_project_directory
from .init_registry import InitCommandSpec, iter_init_command_specs

_MAX_ACTION_DETAILS = 3


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


def _display_path(path: Path) -> str:
    resolved = path.resolve(strict=False)
    cwd = Path.cwd().resolve(strict=False)
    try:
        return str(resolved.relative_to(cwd)) or "."
    except ValueError:
        pass

    home = Path.home().resolve(strict=False)
    try:
        return f"~/{resolved.relative_to(home)}"
    except ValueError:
        return str(path)


def _command_width(plans: Sequence[InitPlan]) -> int:
    return max((len(plan.command) for plan in plans), default=0)


def _render_row(prefix: str, plan: InitPlan, *, command_width: int) -> str:
    return (
        f"  {prefix:<4} init {plan.command:<{command_width}}  {_fallback_summary(plan)}"
    )


def _render_action_details(console: Console, plan: InitPlan) -> None:
    for action in plan.actions[:_MAX_ACTION_DETAILS]:
        detail = f"  {action.detail}" if action.detail else ""
        console.print(
            f"    - {action.operation:<9} {_display_path(action.path)}{detail}"
        )

    remaining = len(plan.actions) - _MAX_ACTION_DETAILS
    if remaining > 0:
        noun = "action" if remaining == 1 else "actions"
        console.print(f"    ... {remaining} more {noun}", style="dim")


def _render_plans(console: Console, plans: Sequence[InitPlan]) -> None:
    console.print("SASE initialization check", style="bold")

    up_to_date = [plan for plan in plans if not plan.has_changes and plan.runnable]
    changed = [plan for plan in plans if plan.has_changes]
    warnings = [(plan, warning) for plan in plans for warning in plan.warnings]
    blockers = [(plan, blocker) for plan in plans for blocker in plan.blockers]
    command_width = _command_width(plans)

    if up_to_date:
        console.print()
        console.print("Up to date:", style="dim")
        for plan in up_to_date:
            console.print(
                _render_row("ok", plan, command_width=command_width), style="dim"
            )

    if changed:
        console.print()
        console.print("Needs attention:", style="bold")
        for plan in changed:
            prefix = "run" if plan.runnable else "hold"
            console.print(_render_row(prefix, plan, command_width=command_width))
            _render_action_details(console, plan)

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
    if plan.command == "sdd" and _plan_may_create_companion_repo(plan):
        prompt += " This may create and push to a GitHub companion repository."
    answer = input_func(f"{prompt} [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


def _plan_may_create_companion_repo(plan: InitPlan) -> bool:
    return any(
        "companion" in action.detail.casefold()
        and "repository" in action.detail.casefold()
        for action in plan.actions
    )


def _apply_args(args: argparse.Namespace, spec: InitCommandSpec) -> argparse.Namespace:
    apply_args = copy.copy(args)
    apply_args.init_subcommand = spec.name
    # Mark the apply as part of bare-``sase init`` onboarding so memory init can
    # derive a managed AGENTS.md title fallback even though ``init_subcommand``
    # now names a spec.
    apply_args.onboarding = True
    if spec.name == "skills":
        apply_args.force = True
    return apply_args


def _plan_specs(
    args: argparse.Namespace,
    specs: Sequence[InitCommandSpec],
) -> tuple[InitPlan, ...]:
    return tuple(spec.plan(args) for spec in specs)


def _active_onboarding_specs(
    specs: Sequence[InitCommandSpec] | None,
) -> tuple[InitCommandSpec, ...]:
    active_specs = tuple(iter_init_command_specs() if specs is None else specs)
    if specs is None and not is_project_directory():
        return tuple(spec for spec in active_specs if spec.name != "sdd")
    return active_specs


def _plan_check_status(plans: Sequence[InitPlan]) -> tuple[bool, bool, bool]:
    has_changes = any(plan.has_changes for plan in plans)
    has_blockers = any(not plan.runnable for plan in plans)
    has_warnings = any(plan.warnings for plan in plans)
    return has_changes, has_blockers, has_warnings


def _render_check_summary(
    console: Console,
    specs: Sequence[InitCommandSpec],
    plans: Sequence[InitPlan],
) -> tuple[bool, bool, bool]:
    has_changes, has_blockers, has_warnings = _plan_check_status(plans)
    if not has_changes and not has_blockers and not has_warnings:
        _render_noop(console, specs)
    else:
        _render_plans(console, plans)
    return has_changes, has_blockers, has_warnings


def run_init_check(
    args: argparse.Namespace,
    *,
    specs: Sequence[InitCommandSpec],
    console: Console | None = None,
) -> int:
    """Run a read-only initialization check and return a process exit code."""
    active_specs = tuple(specs)
    out_console = console or _console_for(sys.stdout)

    if not active_specs:
        _render_no_specs(out_console)
        return 1

    plans = _plan_specs(args, active_specs)
    has_changes, has_blockers, _has_warnings = _render_check_summary(
        out_console,
        active_specs,
        plans,
    )
    if has_blockers:
        return 1
    return 1 if has_changes else 0


def run_init_onboarding(
    args: argparse.Namespace,
    *,
    specs: Sequence[InitCommandSpec] | None = None,
    input_func: Callable[[str], str] = input,
    stdin: TextIO | None = None,
    console: Console | None = None,
) -> int:
    """Run bare ``sase init`` and return a process exit code."""
    if getattr(args, "enable_project_memory", False):
        from .init_memory_handler import prepare_project_memory_opt_in

        if not prepare_project_memory_opt_in(args):
            return 1

    active_specs = _active_onboarding_specs(specs)
    out_console = console or _console_for(sys.stdout)
    is_tty = (stdin or sys.stdin).isatty()

    if not active_specs:
        _render_no_specs(out_console)
        return 1

    plans = _plan_specs(args, active_specs)
    has_changes, has_blockers, _has_warnings = _render_check_summary(
        out_console,
        active_specs,
        plans,
    )

    if has_blockers:
        return 1

    if not has_changes:
        return 0

    if getattr(args, "check", False):
        return 1

    if not getattr(args, "yes", False) and not is_tty:
        out_console.print()
        out_console.print("Run `sase init --yes` to apply these changes.")
        return 1

    spec_by_name = {spec.name: spec for spec in active_specs}
    with defer_chezmoi_deploy() as deferred_chezmoi:
        for plan in plans:
            if not plan.has_changes or not plan.runnable:
                continue
            spec = spec_by_name[plan.command]
            if getattr(args, "yes", False):
                should_run = True
            else:
                try:
                    should_run = _prompt_for_plan(plan, input_func=input_func)
                except EOFError:
                    should_run = False
                except KeyboardInterrupt:
                    out_console.print()
                    out_console.print("init: confirmation cancelled; aborting.")
                    return 1
            if not should_run:
                continue
            exit_code = spec.run(_apply_args(args, spec))
            if exit_code != 0:
                out_console.print()
                out_console.print(
                    f"init {plan.command} failed with exit code {exit_code}.",
                    style="red",
                )
                return exit_code

        deploy_exit_code = deploy_deferred_chezmoi(deferred_chezmoi)
        if deploy_exit_code != 0:
            return deploy_exit_code

    return 0


__all__ = [
    "InitAction",
    "InitPlan",
    "run_init_check",
    "run_init_onboarding",
]
