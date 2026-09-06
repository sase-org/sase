"""Interactive apply workflow for bare ``sase init`` onboarding."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import copy
from typing import TextIO

from rich.console import Console

from ._init_onboarding_types import InitRunResult
from .init_plan import InitPlan
from .init_preview import render_plan_diff
from .init_registry import InitCommandSpec


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
    if plan.command == "repo" and _plan_may_create_sidecar_repo(plan):
        prompt += " This may create and push to a provider sidecar repository."
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


def _plan_may_create_sidecar_repo(plan: InitPlan) -> bool:
    return any(
        "sidecar" in action.detail.casefold()
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


def run_changed_plans(
    args: argparse.Namespace,
    *,
    plans: Sequence[InitPlan],
    specs: Sequence[InitCommandSpec],
    input_func: Callable[[str], str],
    stdin: TextIO,
    console: Console,
) -> InitRunResult:
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
                return InitRunResult(1, "cancelled")
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
            return InitRunResult(exit_code, "failed")

    if skipped:
        # Preserve the single-project coordinator's successful exit when a
        # human declines work, while allowing a batch to report remaining
        # drift in its aggregate status.
        return InitRunResult(0, "needs_attention")
    return InitRunResult(0, "initialized")
