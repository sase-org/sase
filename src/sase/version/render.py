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


def _audit_table(records: Sequence[VersionPackageRecord]) -> Panel:
    sections: list[RenderableType] = []
    for index, record in enumerate(records):
        if index:
            sections.append(Text(""))
        sections.append(_audit_record_table(record))

    return Panel(Group(*sections), title="Package Audit", border_style="blue")


def _audit_record_table(record: VersionPackageRecord) -> Table:
    table = Table.grid(expand=True, padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)
    table.add_column(overflow="fold")

    git = record.git
    table.add_row(
        "Package",
        Text(f"{record.name} ({record.role})", style=_ROLE_STYLES.get(record.role, "")),
    )
    table.add_row("Install", _audit_value(record.install_type))
    table.add_row("Version", _audit_value(record.display_version))
    table.add_row("Dist version", _audit_value(record.distribution_version))
    table.add_row("Source version", _audit_value(record.source_version))
    table.add_row("Git root", _audit_value(git.root if git else None))
    table.add_row("Git commit", _audit_value(git.commit if git else None))
    table.add_row("Git tag", _audit_value(git.tag if git else None))
    table.add_row(
        "Git distance",
        _audit_value(str(git.distance) if git and git.distance is not None else None),
    )
    table.add_row("Git dirty", _audit_value(_yes_no(git.dirty) if git else None))
    table.add_row("Source root", _audit_value(record.source_root))
    table.add_row("Import module", _audit_value(record.import_module))
    table.add_row("Import path", _audit_value(record.import_path))
    table.add_row("Distribution", _audit_value(record.distribution_location))
    return table


def _audit_value(value: str | None) -> Text:
    return Text(value or "-", overflow="fold")


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


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
