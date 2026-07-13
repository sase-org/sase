"""Bare ``sase init`` onboarding coordinator."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
import copy
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Literal, TextIO

from rich.console import Console
from rich.text import Text

from ._init_chezmoi_deploy import defer_chezmoi_deploy, deploy_deferred_chezmoi
from .init_plan import InitAction, InitPlan
from .init_preview import preview_console, render_plan_diff, render_plan_inventory
from .init_project_scope import (
    InitProjectInventory,
    InitProjectTarget,
    is_project_directory,
    resolve_init_project_inventory,
)
from .init_registry import InitCommandSpec, iter_init_command_specs

InitRunStatus = Literal[
    "current",
    "initialized",
    "needs_attention",
    "failed",
    "cancelled",
]


@dataclass(frozen=True)
class _InitRunResult:
    """Structured result for one onboarding run."""

    exit_code: int
    status: InitRunStatus


def _fallback_summary(plan: InitPlan) -> str:
    if plan.summary:
        return plan.summary
    count = len(plan.actions)
    if count == 1:
        action = plan.actions[0]
        detail = f" {action.detail}" if action.detail else ""
        return f"{action.operation} {action.path}{detail}"
    return f"{count} actions"


def _command_width(plans: Sequence[InitPlan]) -> int:
    return max((len(plan.command) for plan in plans), default=0)


def _render_row(prefix: str, plan: InitPlan, *, command_width: int) -> str:
    return (
        f"  {prefix:<4} init {plan.command:<{command_width}}  {_fallback_summary(plan)}"
    )


def _render_plans(
    console: Console,
    plans: Sequence[InitPlan],
    *,
    show_diff: bool = False,
    show_prompt_tip: bool = False,
) -> None:
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
            prefix_style = "green" if plan.runnable else "red"
            row = Text()
            row.append(f"  {prefix:<4}", style=prefix_style)
            row.append(
                f" init {plan.command:<{command_width}}  {_fallback_summary(plan)}"
            )
            console.print(row)
            render_plan_inventory(console, plan)
            if show_diff:
                render_plan_diff(console, plan)

        if show_prompt_tip and not blockers and any(plan.runnable for plan in changed):
            console.print()
            console.print(
                "Tip: answer `d` at a prompt below to review the full diff "
                "before deciding.",
                style="dim",
            )

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
    console.print(
        "Run an explicit subcommand: init memory, init sdd, init skills, or "
        "init workspace."
    )


def _prompt_for_plan(
    plan: InitPlan,
    *,
    input_func: Callable[[str], str],
    console: Console,
) -> bool:
    command = f"sase init {plan.command}"
    if plan.command == "skills":
        command = f"{command} --force"
    prompt = f"Run `{command}` now?"
    if plan.command == "memory":
        prompt += " This may commit and push generated project memory changes."
    if plan.command == "sdd" and _plan_may_create_companion_repo(plan):
        prompt += " This may create and push to a GitHub companion repository."
    while True:
        answer = input_func(f"{prompt} [y/N/d] ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"", "n", "no"}:
            return False
        if answer in {"d", "diff"}:
            render_plan_diff(console, plan)
            continue
        console.print("y = apply, n = skip, d = show diff", style="dim")


def _plan_may_create_companion_repo(plan: InitPlan) -> bool:
    return any(
        "companion" in action.detail.casefold()
        and "repository" in action.detail.casefold()
        for action in plan.actions
    )


def _apply_args(
    args: argparse.Namespace,
    spec: InitCommandSpec,
    *,
    input_func: Callable[[str], str],
    stdin: TextIO,
) -> argparse.Namespace:
    apply_args = copy.copy(args)
    apply_args.init_subcommand = spec.name
    # Mark the apply as part of bare-``sase init`` onboarding so memory init can
    # derive a managed AGENTS.md title fallback even though ``init_subcommand``
    # now names a spec.
    apply_args.onboarding = True
    apply_args._init_input_func = input_func
    apply_args._init_stdin = stdin
    # The coordinator already rendered an explicitly requested preview.
    apply_args.diff = False
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
        return tuple(
            spec for spec in active_specs if spec.name not in {"sdd", "workspace"}
        )
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
    *,
    show_diff: bool = False,
    show_prompt_tip: bool = False,
) -> tuple[bool, bool, bool]:
    has_changes, has_blockers, has_warnings = _plan_check_status(plans)
    if not has_changes and not has_blockers and not has_warnings:
        _render_noop(console, specs)
    else:
        _render_plans(
            console,
            plans,
            show_diff=show_diff,
            show_prompt_tip=show_prompt_tip,
        )
    return has_changes, has_blockers, has_warnings


def run_init_check(
    args: argparse.Namespace,
    *,
    specs: Sequence[InitCommandSpec],
    console: Console | None = None,
) -> int:
    """Run a read-only initialization check and return a process exit code."""
    active_specs = tuple(specs)
    out_console = console or preview_console(sys.stdout)

    if not active_specs:
        _render_no_specs(out_console)
        return 1

    plans = _plan_specs(args, active_specs)
    has_changes, has_blockers, _has_warnings = _render_check_summary(
        out_console,
        active_specs,
        plans,
        show_diff=getattr(args, "diff", False),
    )
    if has_blockers:
        return 1
    return 1 if has_changes else 0


def _run_changed_plans(
    args: argparse.Namespace,
    *,
    plans: Sequence[InitPlan],
    specs: Sequence[InitCommandSpec],
    input_func: Callable[[str], str],
    stdin: TextIO,
    console: Console,
) -> _InitRunResult:
    spec_by_name = {spec.name: spec for spec in specs}
    skipped = False
    for plan in plans:
        if not plan.has_changes or not plan.runnable:
            continue
        spec = spec_by_name[plan.command]
        if getattr(args, "yes", False):
            should_run = True
        else:
            try:
                should_run = _prompt_for_plan(
                    plan,
                    input_func=input_func,
                    console=console,
                )
            except EOFError:
                should_run = False
            except KeyboardInterrupt:
                console.print()
                console.print("init: confirmation cancelled; aborting.")
                return _InitRunResult(1, "cancelled")
        if not should_run:
            skipped = True
            continue
        exit_code = spec.run(
            _apply_args(args, spec, input_func=input_func, stdin=stdin)
        )
        if exit_code != 0:
            console.print()
            console.print(
                f"init {plan.command} failed with exit code {exit_code}.",
                style="red",
            )
            return _InitRunResult(exit_code, "failed")

    if skipped:
        # Preserve the single-project coordinator's successful exit when a
        # human declines work, while allowing a batch to report remaining
        # drift in its aggregate status.
        return _InitRunResult(0, "needs_attention")
    return _InitRunResult(0, "initialized")


def _run_init_onboarding_result(
    args: argparse.Namespace,
    *,
    specs: Sequence[InitCommandSpec] | None = None,
    input_func: Callable[[str], str] = input,
    stdin: TextIO | None = None,
    console: Console | None = None,
    manage_chezmoi_deploy: bool = True,
) -> _InitRunResult:
    """Run one project's onboarding and return a structured result."""
    if getattr(args, "enable_project_memory", False):
        from .init_memory_handler import prepare_project_memory_opt_in

        if not prepare_project_memory_opt_in(args):
            return _InitRunResult(1, "failed")

    active_specs = _active_onboarding_specs(specs)
    out_console = console or preview_console(sys.stdout)
    is_tty = (stdin or sys.stdin).isatty()
    effective_stdin = stdin or sys.stdin

    if not active_specs:
        _render_no_specs(out_console)
        return _InitRunResult(1, "failed")

    plans = _plan_specs(args, active_specs)
    has_changes, has_blockers, _has_warnings = _render_check_summary(
        out_console,
        active_specs,
        plans,
        show_diff=getattr(args, "diff", False),
        show_prompt_tip=(
            is_tty
            and not getattr(args, "yes", False)
            and not getattr(args, "check", False)
        ),
    )

    if has_blockers:
        return _InitRunResult(1, "failed")

    if not has_changes:
        return _InitRunResult(0, "current")

    if getattr(args, "check", False):
        return _InitRunResult(1, "needs_attention")

    if not getattr(args, "yes", False) and not is_tty:
        out_console.print()
        out_console.print("Run `sase init --yes` to apply these changes.")
        return _InitRunResult(1, "needs_attention")

    if not manage_chezmoi_deploy:
        return _run_changed_plans(
            args,
            plans=plans,
            specs=active_specs,
            input_func=input_func,
            stdin=effective_stdin,
            console=out_console,
        )

    with defer_chezmoi_deploy() as deferred_chezmoi:
        result = _run_changed_plans(
            args,
            plans=plans,
            specs=active_specs,
            input_func=input_func,
            stdin=effective_stdin,
            console=out_console,
        )
        if result.exit_code != 0:
            return result

        deploy_exit_code = deploy_deferred_chezmoi(deferred_chezmoi)
        if deploy_exit_code != 0:
            return _InitRunResult(deploy_exit_code, "failed")

    return result


def run_init_onboarding(
    args: argparse.Namespace,
    *,
    specs: Sequence[InitCommandSpec] | None = None,
    input_func: Callable[[str], str] = input,
    stdin: TextIO | None = None,
    console: Console | None = None,
) -> int:
    """Run bare ``sase init`` and return a process exit code."""
    return _run_init_onboarding_result(
        args,
        specs=specs,
        input_func=input_func,
        stdin=stdin,
        console=console,
    ).exit_code


@contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    """Temporarily enter *path* and always restore the caller's directory."""
    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


def _project_args(args: argparse.Namespace) -> argparse.Namespace:
    """Return a fresh namespace for one project in a batch run."""
    project_args = copy.copy(args)
    project_args.all = False
    project_args.enable_project_memory = False
    for marker in (
        "_project_memory_opt_in_prepared",
        "_project_config_changed",
        "_project_config_git_state",
        "_project_config_operation",
    ):
        if hasattr(project_args, marker):
            delattr(project_args, marker)
    return project_args


def _render_project_heading(console: Console, target: InitProjectTarget) -> None:
    console.print()
    console.print(f"Project: {target.reference}", style="bold cyan")
    if target.warnings:
        console.print("Project inventory warnings:", style="yellow")
        for warning in target.warnings:
            console.print(f"  {warning}")


def _summary_parts(
    *,
    checked: int,
    current: int,
    initialized: int,
    needs_attention: int,
    unavailable: int,
    failed: int,
    cancelled: bool,
    deploy_failed: bool,
) -> list[str]:
    parts = [f"{checked} checked"]
    for count, singular in (
        (current, "current"),
        (initialized, "initialized"),
        (needs_attention, "needs attention"),
        (unavailable, "unavailable"),
        (failed, "failed"),
    ):
        if count:
            parts.append(f"{count} {singular}")
    if cancelled:
        parts.append("cancelled")
    if deploy_failed:
        parts.append("deployment failed")
    return parts


def run_init_onboarding_all(
    args: argparse.Namespace,
    *,
    specs: Sequence[InitCommandSpec] | None = None,
    input_func: Callable[[str], str] = input,
    stdin: TextIO | None = None,
    console: Console | None = None,
) -> int:
    """Run bare onboarding for every enabled main SASE project."""
    out_console = console or preview_console(sys.stdout)
    inventory: InitProjectInventory = resolve_init_project_inventory()
    if inventory.error is not None:
        out_console.print(f"init --all: {inventory.error}", style="red")
        return 1
    if not inventory.targets:
        out_console.print("init --all: no enabled main SASE projects were found.")
        return 1

    checked = current = initialized = needs_attention = unavailable = failed = 0
    cancelled = deploy_failed = False

    with defer_chezmoi_deploy() as deferred_chezmoi:
        for target in inventory.targets:
            _render_project_heading(out_console, target)
            if target.unavailable_reason is not None or target.workspace_dir is None:
                unavailable += 1
                reason = target.unavailable_reason or "primary workspace is unavailable"
                out_console.print(f"init --all: {reason}", style="red")
                continue

            checked += 1
            try:
                with _working_directory(target.workspace_dir):
                    result = _run_init_onboarding_result(
                        _project_args(args),
                        specs=specs,
                        input_func=input_func,
                        stdin=stdin,
                        console=out_console,
                        manage_chezmoi_deploy=False,
                    )
            except KeyboardInterrupt:
                out_console.print()
                out_console.print("init --all: cancelled; aborting.")
                cancelled = True
                break
            except Exception as exc:
                out_console.print(
                    f"init --all: project failed: {exc}",
                    style="red",
                )
                failed += 1
                continue

            if result.status == "current":
                current += 1
            elif result.status == "initialized":
                initialized += 1
            elif result.status == "needs_attention":
                needs_attention += 1
            elif result.status == "cancelled":
                cancelled = True
                break
            else:
                failed += 1

        if not cancelled:
            deploy_exit_code = deploy_deferred_chezmoi(deferred_chezmoi)
            deploy_failed = deploy_exit_code != 0

    parts = _summary_parts(
        checked=checked,
        current=current,
        initialized=initialized,
        needs_attention=needs_attention,
        unavailable=unavailable,
        failed=failed,
        cancelled=cancelled,
        deploy_failed=deploy_failed,
    )
    out_console.print()
    out_console.print(f"Initialization summary: {', '.join(parts)}")

    return int(
        cancelled
        or deploy_failed
        or unavailable > 0
        or failed > 0
        or needs_attention > 0
    )


__all__ = [
    "InitAction",
    "InitPlan",
    "run_init_check",
    "run_init_onboarding",
    "run_init_onboarding_all",
]
