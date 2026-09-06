"""Read-only status checks for bare ``sase init`` onboarding."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from rich.console import Console

from ._init_onboarding_rendering import render_no_specs, render_noop, render_plans
from ._init_onboarding_types import InitRunResult
from .init_check_json import cwd_check_row, emit_init_check_json
from .init_plan import InitPlan
from .init_preview import preview_console
from .init_registry import InitCommandSpec


def plan_specs(
    args: argparse.Namespace,
    specs: Sequence[InitCommandSpec],
) -> tuple[InitPlan, ...]:
    return tuple(spec.plan(args) for spec in specs)


def plan_check_status(plans: Sequence[InitPlan]) -> tuple[bool, bool, bool]:
    has_changes = any(plan.has_changes for plan in plans)
    has_blockers = any(not plan.runnable for plan in plans)
    has_warnings = any(plan.warnings for plan in plans)
    return has_changes, has_blockers, has_warnings


def render_check_summary(
    console: Console,
    specs: Sequence[InitCommandSpec],
    plans: Sequence[InitPlan],
    *,
    show_diff: bool = False,
    show_prompt_tip: bool = False,
) -> tuple[bool, bool, bool]:
    has_changes, has_blockers, has_warnings = plan_check_status(plans)
    if not has_changes and not has_blockers and not has_warnings:
        render_noop(console, specs)
    else:
        render_plans(
            console,
            plans,
            show_diff=show_diff,
            show_prompt_tip=show_prompt_tip,
        )
    return has_changes, has_blockers, has_warnings


def _check_result_for_plans(plans: Sequence[InitPlan]) -> InitRunResult:
    has_changes, has_blockers, _has_warnings = plan_check_status(plans)
    if has_blockers:
        return InitRunResult(1, "failed", tuple(plans))
    if not has_changes:
        return InitRunResult(0, "current", tuple(plans))
    return InitRunResult(1, "needs_attention", tuple(plans))


def emit_cwd_check_json(
    plans: Sequence[InitPlan],
    result: InitRunResult,
    *,
    console: Console,
) -> None:
    emit_init_check_json(
        [cwd_check_row(plans, status=result.status)],
        console=console,
    )


def run_init_check(
    args: argparse.Namespace,
    *,
    specs: Sequence[InitCommandSpec],
    console: Console | None = None,
) -> int:
    """Run a read-only initialization check and return a process exit code."""
    active_specs = tuple(specs)
    out_console = console or preview_console(sys.stdout)
    json_mode = bool(getattr(args, "json", False))

    if not active_specs:
        if json_mode:
            result = InitRunResult(1, "failed")
            emit_cwd_check_json((), result, console=out_console)
            return result.exit_code
        render_no_specs(out_console)
        return 1

    plans = plan_specs(args, active_specs)
    result = _check_result_for_plans(plans)
    if json_mode:
        emit_cwd_check_json(plans, result, console=out_console)
        return result.exit_code
    render_check_summary(
        out_console,
        active_specs,
        plans,
        show_diff=getattr(args, "diff", False),
    )
    return result.exit_code
