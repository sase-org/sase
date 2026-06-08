"""Human and JSON output helpers for ``sase version``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.version.inventory import RuntimeVersionInventory, VersionPackageRecord

_ROLE_STYLES = {
    "host": "cyan",
    "core": "magenta",
    "plugin": "green",
}


def runtime_version_inventory_to_json_payload(
    inventory: RuntimeVersionInventory,
) -> dict[str, Any]:
    """Return the stable JSON payload for ``sase version --json``."""
    return {
        "schema_version": 1,
        "runtime": {
            "executable": inventory.executable,
            "python_executable": inventory.python_executable,
            "python_version": inventory.python_version,
        },
        "packages": [record.to_dict() for record in inventory.packages],
    }


def render_runtime_version_inventory(
    inventory: RuntimeVersionInventory,
    *,
    verbose: bool = False,
    console: Console | None = None,
) -> None:
    """Render human output for ``sase version``."""
    target = console or Console()
    renderables: list[RenderableType] = [
        _runtime_panel(inventory),
        _package_table(inventory.packages),
    ]

    if verbose:
        renderables.append(_audit_table(inventory.packages))
        signals = _plugin_signals_table(inventory.packages)
        if signals is not None:
            renderables.append(signals)

    warnings = _warnings_panel(inventory.packages)
    if warnings is not None:
        renderables.append(warnings)

    target.print(Group(*renderables))


def _runtime_panel(inventory: RuntimeVersionInventory) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column(overflow="fold")
    table.add_row("Executable", Text(inventory.executable, overflow="fold"))
    table.add_row(
        "Python",
        Text(
            f"{inventory.python_executable} {inventory.python_version}",
            overflow="fold",
        ),
    )
    return Panel(table, title="SASE Runtime", border_style="cyan")


def _package_table(records: Sequence[VersionPackageRecord]) -> Table:
    has_warnings = any(record.warnings for record in records)
    table = Table(title="Packages", show_header=True, header_style="bold")
    table.add_column("Package", no_wrap=True)
    table.add_column("Role", no_wrap=True)
    if has_warnings:
        table.add_column("Status", no_wrap=True)
    table.add_column("Version", no_wrap=True)
    table.add_column("Code directory", overflow="fold")

    for record in records:
        row: list[RenderableType] = [
            Text(record.name),
            Text(record.role, style=_ROLE_STYLES.get(record.role, "")),
        ]
        if has_warnings:
            row.append(_status_text(record))
        row.extend(
            [
                Text(record.display_version),
                Text(_display_path(record), overflow="fold"),
            ]
        )
        table.add_row(*row)
    return table


def _audit_table(records: Sequence[VersionPackageRecord]) -> Table:
    table = Table(title="Package Audit", show_header=True, header_style="bold")
    table.add_column("Package", no_wrap=True)
    table.add_column("Install", no_wrap=True)
    table.add_column("Dist version", no_wrap=True)
    table.add_column("Source version", no_wrap=True)
    table.add_column("Git", overflow="fold")
    table.add_column("Source root", overflow="fold")
    table.add_column("Import path", overflow="fold")
    table.add_column("Distribution", overflow="fold")

    for record in records:
        table.add_row(
            Text(record.name),
            Text(record.install_type),
            Text(record.distribution_version or "-"),
            Text(record.source_version or "-"),
            Text(_git_summary(record), overflow="fold"),
            Text(record.source_root or "-", overflow="fold"),
            Text(record.import_path or "-", overflow="fold"),
            Text(record.distribution_location or "-", overflow="fold"),
        )
    return table


def _plugin_signals_table(
    records: Sequence[VersionPackageRecord],
) -> Table | None:
    plugin_records = [record for record in records if record.plugin_signals]
    if not plugin_records:
        return None

    table = Table(title="Plugin Signals", show_header=True, header_style="bold")
    table.add_column("Package", no_wrap=True)
    table.add_column("Signals", overflow="fold")
    for record in plugin_records:
        table.add_row(
            Text(record.name),
            Text("\n".join(record.plugin_signals), overflow="fold"),
        )
    return table


def _warnings_panel(records: Sequence[VersionPackageRecord]) -> Panel | None:
    lines: list[str] = []
    for record in records:
        for warning in record.warnings:
            lines.append(f"{record.name}: {warning}")

    if not lines:
        return None

    return Panel(
        Text("\n".join(lines), overflow="fold"),
        title="Warnings",
        border_style="yellow",
    )


def _status_text(record: VersionPackageRecord) -> Text:
    if record.warnings:
        return Text("WARN", style="yellow")
    return Text("OK", style="green")


def _display_path(record: VersionPackageRecord) -> str:
    return (
        record.code_directory
        or record.import_path
        or record.source_root
        or record.distribution_location
        or "-"
    )


def _git_summary(record: VersionPackageRecord) -> str:
    git = record.git
    if git is None:
        return "-"

    parts = [git.short_commit]
    if git.tag:
        parts.append(f"tag {git.tag}")
    if git.distance is not None:
        parts.append(f"distance {git.distance}")
    if git.dirty:
        parts.append("dirty")
    return ", ".join(parts)
