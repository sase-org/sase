"""Rich and JSON rendering for install-mode switches."""

from __future__ import annotations

from typing import Any

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.main.update_json import restart_info_json
from sase.main.update_types import UPDATE_JSON_SCHEMA_VERSION, RestartInfo
from sase.mode_switch.models import (
    ModeSwitchOutcome,
    ModeSwitchResult,
    SwitchPackagePlan,
    SwitchPlan,
    detected_mode_label,
    mode_label,
)
from sase.mode_switch.plan import compare_versions


def render_mode_switch_noop(
    plan: SwitchPlan, *, console: Console | None = None
) -> None:
    target = console or Console()
    label = mode_label(plan.target_mode)
    command = "sase update" if plan.target_mode == "dev" else "sase update --to dev"
    target.print(
        f"Already a {label} install. Run `{command}` to update within this mode."
    )


def render_mode_switch_plan(
    plan: SwitchPlan, *, console: Console | None = None
) -> None:
    target = console or Console()
    target.print(_plan_panel(plan, title="Switch install mode"))


def render_mode_switch_result(
    result: ModeSwitchResult,
    *,
    elapsed: float | None = None,
    quiet: bool = False,
    console: Console | None = None,
) -> None:
    target = console or Console()
    if quiet:
        target.print(_result_summary(result, elapsed))
        return
    body: list[RenderableType] = [_outcomes_table(result.outcomes), Text("")]
    body.append(_result_summary(result, elapsed))
    target.print(
        Panel(
            Group(*body),
            title=f"Switched to {mode_label(result.plan.target_mode)}",
            border_style="cyan",
        )
    )


def mode_switch_dry_run_json(plan: SwitchPlan) -> dict[str, Any]:
    return {
        "schema_version": UPDATE_JSON_SCHEMA_VERSION,
        "dry_run": True,
        "mode": plan.current_mode,
        "switch": _plan_json(plan),
    }


def mode_switch_result_json(
    result: ModeSwitchResult,
    *,
    elapsed: float,
    restart: RestartInfo,
) -> dict[str, Any]:
    return {
        "schema_version": UPDATE_JSON_SCHEMA_VERSION,
        "dry_run": False,
        "mode": result.plan.target_mode,
        "changed": result.changed,
        "elapsed_seconds": round(elapsed, 3),
        "switch": {
            **_plan_json(result.plan),
            "changed": result.changed,
            "packages": [_outcome_json(outcome) for outcome in result.outcomes],
            "executed_commands": [
                _command_json(command) for command in result.commands
            ],
        },
        "restart": restart_info_json(restart),
    }


def _plan_panel(plan: SwitchPlan, *, title: str) -> Panel:
    body: list[RenderableType] = [
        _direction_line(plan),
        Text(""),
        _packages_table(plan),
    ]
    if plan.warnings:
        body.append(Text(""))
        for warning in plan.warnings:
            line = Text()
            line.append("- ", style="yellow")
            line.append(warning, style="yellow")
            body.append(line)
    if plan.commands:
        body.append(Text(""))
        body.append(_commands_table(plan))
    return Panel(Group(*body), title=title, border_style="cyan")


def _direction_line(plan: SwitchPlan) -> Text:
    line = Text()
    line.append(detected_mode_label(plan.current_mode), style="bold")
    line.append("  ->  ", style="dim")
    line.append(mode_label(plan.target_mode), style="bold cyan")
    if plan.dev_root:
        line.append("     dev root ", style="dim")
        line.append(plan.dev_root, style="cyan")
    return line


def _packages_table(plan: SwitchPlan) -> Table:
    table = Table(show_header=True, box=None, pad_edge=False, padding=(0, 2))
    table.add_column("Package", style="bold", no_wrap=True)
    table.add_column("Role", no_wrap=True)
    table.add_column("Current", no_wrap=True)
    table.add_column("Target", no_wrap=True)
    table.add_column("Source")
    for package in plan.packages:
        table.add_row(
            package.name,
            package.role,
            package.current_version or "-",
            _target_cell(package),
            package.source,
        )
    return table


def _commands_table(plan: SwitchPlan) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 1))
    table.add_column(no_wrap=True)
    table.add_column()
    for index, command in enumerate(plan.commands, 1):
        prefix = Text(f"{index}.", style="dim")
        text = Text(" ".join(command.command), style="cyan")
        if command.cwd:
            text.append(f"   (in {command.cwd})", style="dim")
        table.add_row(prefix, text)
    return table


def _outcomes_table(outcomes: tuple[ModeSwitchOutcome, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style="bold", no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column()
    for outcome in outcomes:
        glyph = "." if outcome.status == "stayed-managed" else "+"
        style = "dim" if outcome.status == "stayed-managed" else "green"
        version = Text()
        version.append(outcome.old_version or "-", style="dim")
        version.append(" -> ", style="dim")
        version.append(outcome.new_version or "-", style=style)
        table.add_row(Text(glyph, style=style), outcome.name, version, outcome.source)
    return table


def _target_cell(package: SwitchPackagePlan) -> Text:
    cell = Text()
    current = package.current_version
    target = package.target_version
    comparison = compare_versions(current, target)
    if comparison is not None and comparison < 0:
        cell.append("down ", style="yellow")
    cell.append(target or "-", style="cyan")
    return cell


def _result_summary(result: ModeSwitchResult, elapsed: float | None) -> Text:
    line = Text()
    line.append("Switched to ", style="green")
    line.append(mode_label(result.plan.target_mode), style="bold green")
    if elapsed is not None:
        line.append(f" in {elapsed:.1f}s", style="green")
    stayed = sum(1 for outcome in result.outcomes if outcome.status == "stayed-managed")
    if stayed:
        line.append(f" · {stayed} stayed managed", style="dim")
    return line


def _plan_json(plan: SwitchPlan) -> dict[str, Any]:
    return {
        "current_mode": plan.current_mode,
        "target_mode": plan.target_mode,
        "dev_root": plan.dev_root,
        "changed": plan.changed,
        "packages": [_package_json(package) for package in plan.packages],
        "commands": [_command_json(command) for command in plan.commands],
        "warnings": list(plan.warnings),
        "backup_path": plan.backup_path,
        "restore_command": list(plan.restore_command),
    }


def _package_json(package: SwitchPackagePlan) -> dict[str, Any]:
    return {
        "name": package.name,
        "role": package.role,
        "current_version": package.current_version,
        "target_version": package.target_version,
        "source": package.source,
        "repo_action": package.repo_action,
        "checkout_path": package.checkout_path,
        "repo_url": package.repo_url,
        "warning": package.warning,
    }


def _outcome_json(outcome: ModeSwitchOutcome) -> dict[str, Any]:
    return {
        "name": outcome.name,
        "role": outcome.role,
        "status": outcome.status,
        "old_version": outcome.old_version,
        "new_version": outcome.new_version,
        "source": outcome.source,
    }


def _command_json(command: Any) -> dict[str, Any]:
    return {
        "kind": command.kind,
        "label": command.label,
        "command": list(command.command),
        "cwd": command.cwd,
        "available": command.available,
        "reason": command.reason,
    }
