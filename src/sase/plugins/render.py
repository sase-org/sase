"""Rich rendering for ``sase plugin`` commands."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.plugins.chops import ChopInventory
from sase.plugins.doctor import (
    CheckStatus,
    DoctorCheck,
    DoctorReport,
    aggregate_check_status,
)
from sase.plugins.inventory import PluginEntryPointRecord, PluginInventory

_STATUS_STYLES: dict[CheckStatus, str] = {
    "OK": "green",
    "WARN": "yellow",
    "ERROR": "red",
    "SKIP": "dim",
}


def render_plugin_list(
    plugin_inventory: PluginInventory,
    chop_inventory: ChopInventory,
    checks: tuple[DoctorCheck, ...],
    *,
    verbose: bool = False,
    console: Console | None = None,
) -> None:
    """Render human output for ``sase plugin list``."""
    target = console or Console()
    target.print(
        Group(
            _summary_panel(plugin_inventory, chop_inventory, checks),
            _entry_points_table(plugin_inventory, verbose=verbose),
            _resource_plugins_table(plugin_inventory, verbose=verbose),
            _configured_chops_table(chop_inventory, verbose=verbose),
            _available_chops_table(chop_inventory),
            _install_guidance_panel(plugin_inventory, chop_inventory),
        )
    )


def render_plugin_doctor(
    report: DoctorReport,
    *,
    verbose: bool = False,
    console: Console | None = None,
) -> None:
    """Render human output for ``sase plugin doctor``."""
    target = console or Console()
    target.print(
        Group(
            _doctor_summary_panel(report),
            _checks_table(report.checks, verbose=verbose),
            _resource_plugins_table(report.plugin_inventory, verbose=verbose),
            _configured_chops_table(report.chop_inventory, verbose=verbose),
            _available_chops_table(report.chop_inventory),
            _install_guidance_panel(report.plugin_inventory, report.chop_inventory),
        )
    )


def _summary_panel(
    plugin_inventory: PluginInventory,
    chop_inventory: ChopInventory,
    checks: tuple[DoctorCheck, ...],
) -> Panel:
    status = aggregate_check_status(checks)
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Status", _status_text(status))
    table.add_row("SASE executable", sys.argv[0])
    table.add_row("Python executable", sys.executable)
    table.add_row("Plugin packages", str(len(plugin_inventory.distributions)))
    table.add_row("Entry points", str(len(plugin_inventory.entry_points)))
    table.add_row("Configured chops", str(len(chop_inventory.configured_chops)))
    table.add_row(
        "Available unconfigured chops", str(len(chop_inventory.available_unconfigured))
    )
    return Panel(table, title="SASE Plugins", border_style=_border_style(status))


def _doctor_summary_panel(report: DoctorReport) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Status", _status_text(report.status))
    table.add_row("SASE executable", sys.argv[0])
    table.add_row("Python executable", sys.executable)
    table.add_row("Checks", str(len(report.checks)))
    return Panel(
        table, title="Plugin Doctor", border_style=_border_style(report.status)
    )


def _entry_points_table(
    inventory: PluginInventory,
    *,
    verbose: bool,
) -> Table | Panel:
    if not inventory.entry_points:
        return Panel(
            Text("No SASE entry points were found in this environment.", style="dim"),
            title="Plugin Entry Points",
            border_style="cyan",
        )

    table = Table(title="Plugin Entry Points", show_header=True, header_style="bold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Group", no_wrap=True)
    table.add_column("Name", no_wrap=True)
    table.add_column("Package", no_wrap=True)
    table.add_column("Version", no_wrap=True)
    if verbose:
        table.add_column("Target", overflow="fold")

    for ep in inventory.entry_points:
        row: list[RenderableType] = [
            _status_text(_entry_point_status(ep)),
            Text(ep.group),
            Text(ep.name),
            Text(ep.package),
            Text(ep.version),
        ]
        if verbose:
            row.append(Text(ep.value or "-", overflow="fold"))
        table.add_row(*row)
    return table


def _resource_plugins_table(
    inventory: PluginInventory,
    *,
    verbose: bool,
) -> Table | Panel:
    resources = inventory.resource_entry_points
    if not resources:
        return Panel(
            Text("No resource plugin entry points were found.", style="dim"),
            title="Resource Plugins",
            border_style="cyan",
        )

    table = Table(title="Resource Plugins", show_header=True, header_style="bold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Group", no_wrap=True)
    table.add_column("Name", no_wrap=True)
    table.add_column("Package", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    if verbose:
        table.add_column("Target", overflow="fold")

    for ep in resources:
        detail = _resource_detail(ep)
        row: list[RenderableType] = [
            _status_text(_entry_point_status(ep)),
            Text(ep.group),
            Text(ep.name),
            Text(ep.package),
            Text(detail, overflow="fold"),
        ]
        if verbose:
            row.append(Text(ep.value or "-", overflow="fold"))
        table.add_row(*row)
    return table


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
    table.add_column("Resolution", overflow="fold")
    if verbose:
        table.add_column("Description", overflow="fold")

    for chop in inventory.configured_chops:
        status: CheckStatus
        if chop.status == "configured":
            status = "OK"
        elif chop.status == "missing":
            status = "ERROR"
        else:
            status = "SKIP"
        kind = "agent" if chop.agent else "script"
        resolution = chop.agent or chop.resolved_path or "not found"
        row: list[RenderableType] = [
            _status_text(status),
            Text(chop.lumberjack),
            Text(chop.name),
            Text(kind),
            Text(resolution, overflow="fold"),
        ]
        if verbose:
            row.append(Text(chop.description or "-", overflow="fold"))
        table.add_row(*row)
    return table


def _available_chops_table(inventory: ChopInventory) -> Table | Panel:
    available = inventory.available_unconfigured
    if not available:
        return Panel(
            Text("No available unconfigured chop scripts were found.", style="dim"),
            title="Available Unconfigured Chops",
            border_style="cyan",
        )

    table = Table(
        title="Available Unconfigured Chops",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Status", no_wrap=True)
    table.add_column("Chop", no_wrap=True)
    table.add_column("Source", no_wrap=True)
    table.add_column("Executable", overflow="fold")
    for script in available:
        table.add_row(
            _status_text("WARN"),
            Text(script.name),
            Text(script.source),
            Text(script.executable, overflow="fold"),
        )
    return table


def _checks_table(checks: tuple[DoctorCheck, ...], *, verbose: bool) -> Table:
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


def _install_guidance_panel(
    plugin_inventory: PluginInventory,
    chop_inventory: ChopInventory,
) -> Panel:
    lines = [
        "This command inspects the Python environment that is running this SASE executable.",
        f"Install plugin packages into the same environment as: {sys.executable}",
    ]

    if not plugin_inventory.third_party_entry_points:
        lines.extend(
            [
                "No third-party SASE entry points were found.",
                'Recommended first-party bundle command when available: uv tool install "sase[github]".',
            ]
        )

    if chop_inventory.available_unconfigured:
        lines.append(
            "Available chop scripts are installed but inactive until added under axe.lumberjacks in sase.yml."
        )

    if any(chop.status == "missing" for chop in chop_inventory.configured_chops):
        lines.append(
            "Missing configured chops usually mean the package was installed into a different environment or the script name changed."
        )

    return Panel(Text("\n".join(lines)), title="Install Guidance", border_style="dim")


def _entry_point_status(ep: PluginEntryPointRecord) -> CheckStatus:
    if ep.load_status == "error":
        return "ERROR"
    if ep.load_status == "skipped":
        return "SKIP"
    return "OK"


def _resource_detail(ep: PluginEntryPointRecord) -> str:
    if ep.load_status == "ok":
        return "loaded"
    if ep.load_status == "skipped":
        return "disabled by " + ", ".join(ep.disabled_by)
    if ep.load_status == "error":
        return ep.load_error or "load failed"
    return "metadata only"


def _status_text(status: CheckStatus) -> Text:
    return Text(status, style=_STATUS_STYLES[status])


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
