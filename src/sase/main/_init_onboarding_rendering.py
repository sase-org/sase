"""Console rendering for bare ``sase init`` onboarding."""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console
from rich.text import Text

from .init_plan import InitPlan
from .init_preview import render_plan_diff, render_plan_inventory
from .init_registry import InitCommandSpec


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


def render_plans(
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


def render_noop(console: Console, specs: Sequence[InitCommandSpec]) -> None:
    checked = ", ".join(spec.name for spec in specs)
    console.print("SASE is initialized. No init subcommands need to run.")
    console.print(f"Checked: {checked}.")


def render_no_specs(console: Console) -> None:
    console.print("SASE initialization check", style="bold")
    console.print()
    console.print("No init planners are registered yet.")
    console.print(
        "Run an explicit subcommand: init config, init memory, init repo, or init skills."
    )
