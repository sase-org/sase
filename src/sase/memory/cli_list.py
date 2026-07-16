"""Rich rendering for ``sase memory list``."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.main.init_memory.config import project_memory_name
from sase.memory.inventory import (
    MemoryEntryStatus,
    MemoryContextRoot,
    MemoryFileEntry,
    MemoryInventory,
    MemoryReference,
    build_memory_inventory,
    display_path_for_context,
)

_STATUS_STYLES: dict[MemoryEntryStatus, str] = {
    "loaded": "green",
    "referenced": "yellow",
    "available": "dim",
    "missing": "red",
}


def handle_memory_list_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Render memory files visible from the current launch context."""
    _ = args
    root = Path.cwd()
    inventory = build_memory_inventory(root, home_root=Path.home())
    _render_memory_inventory(
        inventory,
        console=console,
        project_name=project_memory_name(root),
    )


def _render_memory_inventory(
    inventory: MemoryInventory,
    *,
    console: Console | None = None,
    project_name: str | None = None,
) -> None:
    """Print a Rich dashboard for ``inventory``."""
    target = console or Console()
    target.print(
        _build_memory_inventory_dashboard(inventory, project_name=project_name)
    )


def _build_memory_inventory_dashboard(
    inventory: MemoryInventory, *, project_name: str | None = None
) -> Group:
    """Build the static Rich dashboard for a memory inventory."""
    return Group(
        _summary_panel(inventory, project_name=project_name),
        _entries_panel(inventory),
        _notes_panel(),
    )


def _summary_panel(
    inventory: MemoryInventory, *, project_name: str | None = None
) -> Panel:
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()

    roots = ", ".join(
        _display_path_for_inventory(inventory, path)
        for path in inventory.instruction_roots
    )
    if not roots:
        roots = "none found"

    summary.add_row("Directory", str(inventory.root))
    summary.add_row("Project", project_name or "-")
    summary.add_row(
        "Instruction roots", f"{len(inventory.instruction_roots)} ({roots})"
    )
    summary.add_row("Loaded files", str(inventory.loaded_count))
    summary.add_row("Referenced-only files", str(inventory.referenced_count))
    summary.add_row("Available files", str(inventory.available_count))
    summary.add_row("Missing references", str(inventory.missing_count))
    summary.add_row("Loaded lines", str(inventory.loaded_stats.line_count))
    summary.add_row(
        "Approx loaded tokens", str(inventory.loaded_stats.approx_token_count)
    )

    return Panel(summary, title="SASE Memory Context", border_style="cyan")


def _entries_panel(inventory: MemoryInventory) -> Panel:
    title = f"Context Files ({len(inventory.entries)})"
    if not inventory.entries:
        return Panel(
            Text("No memory files or references found.", style="dim"),
            title=title,
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Status", no_wrap=True)
    table.add_column("Path")
    table.add_column("Lines", justify="right", no_wrap=True)
    table.add_column("Approx tokens", justify="right", no_wrap=True)
    table.add_column("Reference detail")

    for entry in inventory.entries:
        row_style = "dim" if entry.status == "available" else None
        table.add_row(
            Text(entry.status, style=_STATUS_STYLES[entry.status]),
            Text(entry.relative_path),
            _stats_value(entry.stats.line_count if entry.stats is not None else None),
            _stats_value(
                entry.stats.approx_token_count if entry.stats is not None else None
            ),
            _reference_detail(inventory, entry),
            style=row_style,
        )

    return Panel(table, title=title, border_style="cyan")


def _notes_panel() -> Panel:
    notes = Text()
    notes.append("@path loads file contents into agent context.\n")
    notes.append("AGENTS.md is counted because it is loaded instruction context.\n")
    notes.append("Plain sase/memory/... paths are visible references only.")
    return Panel(notes, title="Notes", border_style="dim")


def _stats_value(value: int | None) -> str:
    if value is None:
        return "-"
    return str(value)


def _reference_detail(inventory: MemoryInventory, entry: MemoryFileEntry) -> Text:
    if not entry.references:
        if entry.status == "available":
            return Text("present on disk, not reached", style="dim")
        return Text("-", style="dim")

    first = entry.references[0]
    detail = _format_reference(inventory, first)
    extra_count = len(entry.references) - 1
    if extra_count:
        detail.append(f" (+{extra_count} refs)", style="dim")
    return detail


def _format_reference(inventory: MemoryInventory, reference: MemoryReference) -> Text:
    source = _display_path_for_inventory(inventory, reference.source)
    marker = "@" if reference.kind == "loaded" else ""
    detail = Text()
    detail.append(source)
    detail.append(" -> ", style="dim")
    detail.append(f"{marker}{reference.token}")
    return detail


def _display_path_for_inventory(inventory: MemoryInventory, path: Path) -> str:
    context_roots = inventory.context_roots
    if not context_roots:
        context_roots = (
            MemoryContextRoot(
                root=inventory.root.resolve(strict=False), kind="project"
            ),
        )
    return display_path_for_context(context_roots, path)
