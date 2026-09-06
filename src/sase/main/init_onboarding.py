"""Bare ``sase init`` onboarding coordinator."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import sys
from typing import Any, TextIO

from rich.console import Console

from sase.memory.locks import LockTimeoutError

from ._init_chezmoi_deploy import (
    defer_chezmoi_deploy,
    deploy_deferred_chezmoi,
    print_chezmoi_deploy_lock_timeout,
)
from ._init_onboarding_apply import run_changed_plans
from ._init_onboarding_batch import (
    project_args,
    render_project_heading,
    summary_parts,
    tally_batch_status,
    working_directory,
)
from ._init_onboarding_check import (
    emit_cwd_check_json,
    plan_check_status,
    plan_specs,
    render_check_summary,
    run_init_check,
)
from ._init_onboarding_rendering import render_no_specs
from ._init_onboarding_types import InitRunResult, result_with_plans
from .init_check_json import emit_init_check_json, target_check_row
from .init_plan import InitAction, InitPlan
from .init_preview import preview_console
from .init_project_scope import (
    InitProjectInventory,
    InitProjectTarget,
    is_project_directory,
    resolve_init_project_inventory,
    select_init_project_targets,
)
from .init_registry import InitCommandSpec, iter_init_command_specs

__all__ = [
    "InitAction",
    "InitPlan",
    "run_init_check",
    "run_init_onboarding",
    "run_init_onboarding_all",
]


def _active_onboarding_specs(
    specs: Sequence[InitCommandSpec] | None,
) -> tuple[InitCommandSpec, ...]:
    active_specs = tuple(iter_init_command_specs() if specs is None else specs)
    if specs is None and not is_project_directory():
        return tuple(spec for spec in active_specs if spec.name != "repo")
    return active_specs


def _run_init_onboarding_result(
    args: argparse.Namespace,
    *,
    specs: Sequence[InitCommandSpec] | None = None,
    input_func: Callable[[str], str] = input,
    stdin: TextIO | None = None,
    console: Console | None = None,
    manage_chezmoi_deploy: bool = True,
    render: bool = True,
    emit_json: bool | None = None,
) -> InitRunResult:
    """Run one project's onboarding and return a structured result."""
    json_mode = bool(getattr(args, "json", False)) if emit_json is None else emit_json
    should_render = render and not json_mode
    if getattr(args, "enable_project_memory", False):
        from .init_memory_handler import prepare_project_memory_opt_in

        if not prepare_project_memory_opt_in(args):
            return InitRunResult(1, "failed")

    active_specs = _active_onboarding_specs(specs)
    out_console = console or preview_console(sys.stdout)
    is_tty = (stdin or sys.stdin).isatty()
    effective_stdin = stdin or sys.stdin

    if not active_specs:
        result = InitRunResult(1, "failed")
        if json_mode:
            emit_cwd_check_json((), result, console=out_console)
            return result
        if should_render:
            render_no_specs(out_console)
        return result

    plans = plan_specs(args, active_specs)
    if should_render:
        has_changes, has_blockers, _has_warnings = render_check_summary(
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
    else:
        has_changes, has_blockers, _has_warnings = plan_check_status(plans)

    if has_blockers:
        result = InitRunResult(1, "failed", tuple(plans))
    elif not has_changes:
        result = InitRunResult(0, "current", tuple(plans))
    elif getattr(args, "check", False):
        result = InitRunResult(1, "needs_attention", tuple(plans))
    elif not getattr(args, "yes", False) and not is_tty:
        if should_render:
            out_console.print()
            out_console.print("Run `sase init --yes` to apply these changes.")
        result = InitRunResult(1, "needs_attention", tuple(plans))
    elif not manage_chezmoi_deploy:
        result = result_with_plans(
            run_changed_plans(
                args,
                plans=plans,
                specs=active_specs,
                input_func=input_func,
                stdin=effective_stdin,
                console=out_console,
            ),
            plans,
        )
    else:
        try:
            with defer_chezmoi_deploy() as deferred_chezmoi:
                result = result_with_plans(
                    run_changed_plans(
                        args,
                        plans=plans,
                        specs=active_specs,
                        input_func=input_func,
                        stdin=effective_stdin,
                        console=out_console,
                    ),
                    plans,
                )
                if result.exit_code == 0:
                    deploy_exit_code = deploy_deferred_chezmoi(deferred_chezmoi)
                    if deploy_exit_code != 0:
                        result = InitRunResult(deploy_exit_code, "failed", tuple(plans))
        except LockTimeoutError as exc:
            if should_render:
                print_chezmoi_deploy_lock_timeout("init", exc)
            result = InitRunResult(1, "failed", tuple(plans))

    if json_mode:
        emit_cwd_check_json(plans, result, console=out_console)
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


def run_init_onboarding_all(
    args: argparse.Namespace,
    *,
    specs: Sequence[InitCommandSpec] | None = None,
    input_func: Callable[[str], str] = input,
    stdin: TextIO | None = None,
    console: Console | None = None,
    targets: Sequence[InitProjectTarget] | None = None,
) -> int:
    """Run bare onboarding for every enabled main SASE project."""
    out_console = console or preview_console(sys.stdout)
    json_mode = bool(getattr(args, "json", False))
    names = getattr(args, "project", None)
    scope = "init --project" if names else "init --all"
    if targets is None:
        inventory: InitProjectInventory = resolve_init_project_inventory()
        if inventory.error is not None:
            out_console.print(f"{scope}: {inventory.error}", style="red")
            return 1
        if names:
            inventory = select_init_project_targets(inventory, names)
            if inventory.error is not None:
                out_console.print(f"{scope}: {inventory.error}", style="red")
                return 1
        if not inventory.targets:
            empty = (
                "no matching enabled main SASE projects were found."
                if names
                else "no enabled main SASE projects were found."
            )
            out_console.print(f"{scope}: {empty}")
            return 1
        selected = inventory.targets
    else:
        selected = tuple(targets)

    checked = current = initialized = needs_attention = unavailable = failed = 0
    cancelled = deploy_failed = False
    project_rows: list[dict[str, Any]] = []

    try:
        with defer_chezmoi_deploy() as deferred_chezmoi:
            for target in selected:
                if not json_mode:
                    render_project_heading(out_console, target)
                if (
                    target.unavailable_reason is not None
                    or target.workspace_dir is None
                ):
                    unavailable += 1
                    reason = (
                        target.unavailable_reason or "primary workspace is unavailable"
                    )
                    if json_mode:
                        project_rows.append(target_check_row(target, status="failed"))
                    else:
                        out_console.print(f"{scope}: {reason}", style="red")
                    continue

                checked += 1
                try:
                    with working_directory(target.workspace_dir):
                        result = _run_init_onboarding_result(
                            project_args(args),
                            specs=specs,
                            input_func=input_func,
                            stdin=stdin,
                            console=out_console,
                            manage_chezmoi_deploy=False,
                            render=not json_mode,
                            emit_json=False,
                        )
                except KeyboardInterrupt:
                    cancelled = True
                    if json_mode:
                        project_rows.append(
                            target_check_row(target, status="cancelled")
                        )
                    else:
                        out_console.print()
                        out_console.print(f"{scope}: cancelled; aborting.")
                    break
                except Exception as exc:
                    failed += 1
                    if json_mode:
                        project_rows.append(
                            target_check_row(target, status="failed", error=str(exc))
                        )
                    else:
                        out_console.print(
                            f"{scope}: project failed: {exc}",
                            style="red",
                        )
                    continue

                if json_mode:
                    project_rows.append(
                        target_check_row(
                            target, status=result.status, plans=result.plans
                        )
                    )
                (
                    current,
                    initialized,
                    needs_attention,
                    failed,
                    batch_cancelled,
                ) = tally_batch_status(
                    result.status,
                    current=current,
                    initialized=initialized,
                    needs_attention=needs_attention,
                    failed=failed,
                )
                if batch_cancelled:
                    cancelled = True
                    break

            if not cancelled:
                deploy_exit_code = deploy_deferred_chezmoi(deferred_chezmoi)
                deploy_failed = deploy_exit_code != 0
    except LockTimeoutError as exc:
        if not json_mode:
            print_chezmoi_deploy_lock_timeout(scope, exc)
        deploy_failed = True

    if json_mode:
        emit_init_check_json(project_rows, console=out_console)
    else:
        parts = summary_parts(
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
