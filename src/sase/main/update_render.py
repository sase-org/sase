"""Rich renderers for editable-package ``sase update`` output."""

from __future__ import annotations

from typing import Any

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.dev_update import (
    DevReconcileStep,
    DevUpdateOutcome,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateResult,
    DevUpdateRootPlan,
)
from sase.dev_update.code_swap_lock import code_swap_advisory_warning
from sase.main.update_state import dev_counts, humanize_duration, plural
from sase.uv_tool.render import PlannedPackage


def render_dev_update_dry_run(
    plan: DevUpdatePlan,
    *,
    managed_argv: list[str],
    managed_packages: tuple[PlannedPackage, ...],
    console: Console,
) -> None:
    body: list[RenderableType] = []
    if plan.packages:
        body.append(_dev_plan_table(plan.packages))
    else:
        body.append(Text("No editable packages found.", style="dim"))

    if plan.roots:
        body.append(Text(""))
        body.append(_dev_roots_table(plan.roots))

    if plan.reconcile_steps:
        body.append(Text(""))
        body.append(_dev_reconcile_table(plan.reconcile_steps))

    if managed_argv:
        body.append(Text(""))
        command = Text()
        command.append("Would also run  ", style="dim")
        command.append(" ".join(managed_argv), style="cyan")
        body.append(command)
        if managed_packages:
            body.append(_planned_table_for_dev_panel(managed_packages))

    if (advisory := _advisory_warning_line()) is not None:
        body.append(Text(""))
        body.append(advisory)

    body.append(Text(""))
    note = Text()
    note.append("Dry run — nothing was changed. Re-run as ", style="dim")
    note.append("sase update", style="cyan")
    note.append(" to update.", style="dim")
    body.append(note)
    console.print(
        Panel(Group(*body), title="SASE Update (dry run)", border_style="cyan")
    )


def render_dev_update_result(
    result: DevUpdateResult,
    *,
    elapsed: float,
    quiet: bool,
    console: Console,
    failed: bool,
) -> None:
    if quiet:
        console.print(_dev_quiet_line(result, elapsed, failed=failed))
        return

    body: list[RenderableType] = [_dev_outcomes_table(result.outcomes)]
    reconcile = tuple(
        cmd for cmd in result.commands if not cmd.label.startswith("git ")
    )
    if reconcile:
        body.append(Text(""))
        body.append(_dev_executed_commands_table(reconcile))
    if (advisory := _advisory_warning_line()) is not None:
        body.append(Text(""))
        body.append(advisory)
    body.append(Text(""))
    body.append(_dev_summary_line(result, elapsed, failed=failed))
    console.print(
        Panel(
            Group(*body),
            title="SASE Dev Update",
            border_style="red" if failed else "cyan",
        )
    )


def _dev_plan_table(packages: tuple[DevUpdatePackagePlan, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style="bold", no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column()
    for package in packages:
        table.add_row(
            _dev_plan_glyph(package),
            Text(package.record.name),
            _dev_plan_version_cell(package),
            Text(package.reason, style="dim"),
        )
    return table


def _dev_roots_table(roots: tuple[DevUpdateRootPlan, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style="dim")
    table.add_column()
    for root in roots:
        label = "fetch + fast-forward" if root.status == "actionable" else "skip"
        table.add_row(Text("git", style="cyan"), Text(root.git_root), Text(label))
    return table


def _dev_reconcile_table(steps: tuple[DevReconcileStep, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style="bold")
    table.add_column()
    for step in steps:
        command = (
            " ".join(step.command) if step.command else step.reason or "unavailable"
        )
        if step.repair_command:
            command = f"{command} (fallback: {' '.join(step.repair_command)})"
        table.add_row(Text("reconcile", style="cyan"), Text(step.label), Text(command))
    return table


def _planned_table_for_dev_panel(packages: tuple[PlannedPackage, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column()
    for package in packages:
        table.add_row(
            Text(package.name),
            Text(package.current_version or "—", style="dim"),
            Text(package.role, style="dim"),
        )
    return table


def _dev_outcomes_table(outcomes: tuple[DevUpdateOutcome, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style="bold", no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column()
    for outcome in outcomes:
        table.add_row(
            _dev_outcome_glyph(outcome),
            Text(outcome.record.name),
            _dev_outcome_version_cell(outcome),
            Text(outcome.reason, style="red" if outcome.status == "failed" else "dim"),
        )
    return table


def _dev_executed_commands_table(commands: tuple[Any, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style="bold")
    table.add_column()
    for command in commands:
        rendered = " ".join(command.command)
        table.add_row(
            Text("ran" if command.returncode == 0 else "failed", style="cyan"),
            Text(command.label),
            Text(rendered, style="dim"),
        )
    return table


def _dev_plan_glyph(package: DevUpdatePackagePlan) -> Text:
    if package.status == "actionable":
        return Text("↑", style="green")
    return Text("·", style="dim")


def _dev_outcome_glyph(outcome: DevUpdateOutcome) -> Text:
    if outcome.status == "updated":
        return Text("✓", style="green")
    if outcome.status == "failed":
        return Text("✗", style="red")
    return Text("·", style="dim")


def _dev_plan_version_cell(package: DevUpdatePackagePlan) -> Text:
    return _transition_cell(package.current_version, package.latest_version)


def _dev_outcome_version_cell(outcome: DevUpdateOutcome) -> Text:
    return _transition_cell(outcome.old_version, outcome.new_version)


def _transition_cell(old: str | None, new: str | None) -> Text:
    cell = Text()
    cell.append(old or "—", style="dim")
    if new and new != old:
        cell.append(" → ", style="dim")
        cell.append(new, style="green")
    return cell


def _advisory_warning_line() -> Text | None:
    warning = code_swap_advisory_warning()
    if warning is None:
        return None
    return Text(f"⚠ {warning}", style="yellow")


def _dev_summary_line(result: DevUpdateResult, elapsed: float, *, failed: bool) -> Text:
    counts = dev_counts(result)
    updated = counts["updated"]
    skipped = counts["skipped"]
    failed_count = counts["failed"]
    line = Text()
    if failed:
        line.append("Dev update failed", style="red")
    elif updated:
        line.append("Updated ", style="green")
        line.append(
            f"{updated} editable {plural(updated, 'package')}", style="bold green"
        )
    else:
        line.append("No editable checkouts updated", style="dim")
    line.append(f" in {humanize_duration(elapsed)}", style="dim")
    if skipped:
        line.append(f" · {skipped} skipped", style="dim")
    if failed_count:
        line.append(f" · {failed_count} failed", style="red")
    return line


def _dev_quiet_line(result: DevUpdateResult, elapsed: float, *, failed: bool) -> Text:
    return _dev_summary_line(result, elapsed, failed=failed)
