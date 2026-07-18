"""Rich rendering for ``sase axe chop list`` and ``sase axe chop doctor``."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from sase.axe.chop_doctor import ChopCheck, ChopDoctorReport
from sase.axe.chop_inventory import ChopInventory, ConfiguredChopRecord
from sase.diagnostics import CheckStatus

_STATUS_STYLES: dict[CheckStatus, str] = {
    "OK": "green",
    "WARN": "yellow",
    "ERROR": "red",
    "SKIP": "dim",
}


def render_chop_list(
    inventory: ChopInventory,
    *,
    available: bool = False,
    verbose: bool = False,
    console: Console | None = None,
) -> None:
    """Render human output for ``sase axe chop list``."""
    target = console or Console()
    renderables: list[RenderableType] = [
        _configured_chops_table(inventory, verbose=verbose)
    ]
    if available:
        renderables.append(_available_chops_table(inventory, verbose=verbose))
    if verbose:
        renderables.append(_search_dirs_panel(inventory))
    target.print(Group(*renderables))


def render_chop_doctor(
    report: ChopDoctorReport,
    *,
    verbose: bool = False,
    console: Console | None = None,
) -> None:
    """Render human output for ``sase axe chop doctor``."""
    target = console or Console()
    target.print(
        Group(
            _doctor_summary_panel(report),
            _checks_table(report.checks, verbose=verbose),
            _configured_chops_table(report.inventory, verbose=verbose),
            _available_chops_table(report.inventory, verbose=verbose),
        )
    )


def render_chop_run_result(
    result: Mapping[str, Any],
    proposals: Sequence[Mapping[str, Any]],
    *,
    dry_run: bool,
    verbose: bool,
    console: Console | None = None,
) -> None:
    """Render one normalized structured result and its proposal previews."""
    target = console or Console()
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold cyan")
    summary.add_column(overflow="fold")
    summary.add_row("Status", str(result.get("status", "-")))
    summary.add_row("Summary", str(result.get("summary") or "-"))
    summary.add_row("Reason", str(result.get("reason") or "-"))
    counters = result.get("counters")
    summary.add_row(
        "Counters",
        json.dumps(counters, sort_keys=True) if isinstance(counters, dict) else "-",
    )
    renderables: list[RenderableType] = [
        Panel(
            summary,
            title="Chop Result" + (" (dry run)" if dry_run else ""),
            border_style="cyan",
        )
    ]

    if proposals:
        table = Table(
            title="Validated Agent Proposals",
            show_header=True,
            header_style="bold",
        )
        table.add_column("#", justify="right", no_wrap=True)
        table.add_column("ID", no_wrap=True)
        table.add_column("Validation", no_wrap=True)
        table.add_column("Agent", overflow="fold")
        table.add_column("Workspace", overflow="fold")
        table.add_column("Wait On", overflow="fold")
        table.add_column("Model", overflow="fold")
        table.add_column("Dedupe", overflow="fold")
        table.add_column("Env", overflow="fold")
        for proposal in proposals:
            validation = str(proposal.get("validation") or "valid")
            table.add_row(
                str(int(proposal.get("index", 0)) + 1),
                str(proposal.get("id") or "-"),
                Text(
                    validation,
                    style="yellow" if validation == "duplicate" else "green",
                ),
                str(proposal.get("agent_name") or "-"),
                str(proposal.get("workspace") or "-"),
                str(proposal.get("wait_name") or "-"),
                str(proposal.get("model") or "-"),
                str(proposal.get("dedupe_key") or "-"),
                ", ".join(str(v) for v in proposal.get("env_names", [])) or "-",
            )
        renderables.append(table)
    else:
        renderables.append(
            Panel(
                Text("No agent launches proposed.", style="dim"),
                title="Validated Agent Proposals",
                border_style="dim",
            )
        )

    if verbose:
        renderables.append(
            Panel(
                Syntax(
                    json.dumps(dict(result), indent=2, sort_keys=True),
                    "json",
                    word_wrap=True,
                ),
                title="Full Result Document",
                border_style="magenta",
            )
        )
        for proposal in proposals:
            renderables.append(
                Panel(
                    Text(str(proposal.get("prompt") or ""), overflow="fold"),
                    title=f"Proposal {int(proposal.get('index', 0)) + 1} Scaffold",
                    border_style="dim",
                )
            )
    target.print(Group(*renderables))


def _doctor_summary_panel(report: ChopDoctorReport) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Status", _status_text(report.status))
    table.add_row("Configured chops", str(len(report.inventory.configured_chops)))
    table.add_row(
        "Available unconfigured chops",
        str(len(report.inventory.available_unconfigured)),
    )
    table.add_row("Checks", str(len(report.checks)))
    return Panel(table, title="Chop Doctor", border_style=_border_style(report.status))


def _configured_chops_table(
    inventory: ChopInventory,
    *,
    verbose: bool,
) -> Table | Panel:
    if not inventory.configured_chops:
        return Panel(
            Text("No chops are configured under axe.lumberjacks.", style="dim"),
            title="Configured Chops",
            border_style="cyan",
        )

    table = Table(title="Configured Chops", show_header=True, header_style="bold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Lumberjack", no_wrap=True)
    table.add_column("Chop", no_wrap=True)
    table.add_column("Kind", no_wrap=True)
    table.add_column("Last Run", no_wrap=True)
    table.add_column("Resolution", overflow="fold")
    if verbose:
        table.add_column("Description", overflow="fold")
        table.add_column("Policy / Last Decision", overflow="fold")

    for chop in inventory.configured_chops:
        resolution = (
            f"{chop.script} → {chop.resolved_path}"
            if chop.resolved_path
            else f"{chop.script} → not found"
        )
        row: list[RenderableType] = [
            _status_text(_configured_chop_status(chop)),
            Text(chop.lumberjack),
            Text(chop.name),
            Text("script"),
            _run_status_text(chop.latest_run_status),
            Text(resolution, overflow="fold"),
        ]
        if verbose:
            row.append(Text(chop.description or "-", overflow="fold"))
            row.append(Text(_chop_policy_summary(chop), overflow="fold"))
        table.add_row(*row)
    return table


def _available_chops_table(
    inventory: ChopInventory,
    *,
    verbose: bool,
) -> Table | Panel:
    available = inventory.available_scripts
    if not available:
        return Panel(
            Text("No executable chop scripts were found.", style="dim"),
            title="Available Chops",
            border_style="cyan",
        )

    table = Table(title="Available Chops", show_header=True, header_style="bold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Chop", no_wrap=True)
    table.add_column("Configured", no_wrap=True)
    if verbose:
        table.add_column("Source", no_wrap=True)
    table.add_column("Executable", overflow="fold")
    for script in available:
        status: CheckStatus = "OK" if script.configured else "WARN"
        row: list[RenderableType] = [
            _status_text(status),
            Text(script.name),
            Text("yes" if script.configured else "no"),
        ]
        if verbose:
            row.append(Text(script.source))
        row.append(Text(script.executable, overflow="fold"))
        table.add_row(*row)
    return table


def _search_dirs_panel(inventory: ChopInventory) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column(overflow="fold")
    table.add_row("Python bin dir", inventory.python_bin_dir)
    table.add_row(
        "Chop script dirs",
        "\n".join(inventory.chop_script_dirs) or "-",
    )
    table.add_row("PATH dirs", str(len(inventory.path_dirs)))
    return Panel(table, title="Search Dirs", border_style="dim")


def _checks_table(checks: tuple[ChopCheck, ...], *, verbose: bool) -> Table:
    table = Table(title="Checks", show_header=True, header_style="bold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Check", overflow="fold")
    table.add_column("Details", overflow="fold")
    table.add_column("Next Step", overflow="fold")
    if verbose:
        table.add_column("ID", overflow="fold")

    for check in checks:
        row: list[RenderableType] = [
            _status_text(check.status),
            Text(check.summary, overflow="fold"),
            Text(_join_lines(check.details), overflow="fold"),
            Text(_join_lines(check.next_steps), overflow="fold"),
        ]
        if verbose:
            row.append(Text(check.id, overflow="fold"))
        table.add_row(*row)
    return table


def _configured_chop_status(chop: ConfiguredChopRecord) -> CheckStatus:
    if chop.status == "configured":
        return "OK"
    if chop.status == "missing":
        return "ERROR"
    return "ERROR"


def _chop_policy_summary(chop: ConfiguredChopRecord) -> str:
    parts: list[str] = []
    provider = str(chop.trigger.get("provider") or "always")
    parts.append(f"trigger={provider}")
    if chop.inhibit_if:
        guards = ",".join(str(guard.get("provider")) for guard in chop.inhibit_if)
        parts.append(f"guards={guards}")
    if chop.once_per is not None:
        parts.append(f"once_per={chop.once_per.get('key')}")
    if chop.latest_run_reason:
        parts.append(f"last={chop.latest_run_reason}")
    return "\n".join(parts)


def _status_text(status: CheckStatus) -> Text:
    return Text(status, style=_STATUS_STYLES[status])


def _run_status_text(status: str | None) -> Text:
    labels: dict[str, tuple[str, str]] = {
        "running": ("running", "green"),
        "success": ("success", "green"),
        "failure": ("failure", "red"),
        "timeout": ("timeout", "yellow"),
        "missing_script": ("missing", "yellow"),
        "skipped": ("skipped", "yellow"),
        "no_op": ("no-op", "cyan"),
        "check_error": ("check error", "yellow"),
        "launched": ("launched", "cyan"),
        "action_succeeded": ("action succeeded", "green"),
        "action_failed": ("action failed", "red"),
    }
    if status is None:
        return Text("never", style="dim")
    label, style = labels.get(status, (status, "dim"))
    return Text(label, style=style)


def _border_style(status: CheckStatus) -> str:
    if status == "ERROR":
        return "red"
    if status == "WARN":
        return "yellow"
    if status == "SKIP":
        return "dim"
    return "cyan"


def _join_lines(lines: Sequence[str]) -> str:
    return "\n".join(lines) if lines else "-"
