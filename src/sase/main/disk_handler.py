"""Handler implementation for the ``sase disk`` CLI group."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.table import Table

from sase.core.disk_footprint import (
    DiskFootprintReport,
    DiskReapResult,
    collect_disk_footprint,
    format_bytes,
    run_disk_reap,
)


def handle_disk_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase disk ...`` command."""

    subcommand = getattr(args, "disk_subcommand", None)
    if subcommand == "list":
        sys.exit(_handle_list(args))
    if subcommand == "reap":
        sys.exit(_handle_reap(args))
    print("Usage: sase disk {list,reap}", file=sys.stderr)
    sys.exit(2)


def _handle_list(args: argparse.Namespace) -> int:
    report = collect_disk_footprint()
    if getattr(args, "json", False):
        print(json.dumps(report.to_json_dict(), indent=2, sort_keys=True))
        return 0
    _print_disk_report(report)
    return 0


def _handle_reap(args: argparse.Namespace) -> int:
    result = run_disk_reap(
        apply=bool(getattr(args, "apply", False)),
        project=getattr(args, "project", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(result.to_json_dict(), indent=2, sort_keys=True))
        return _exit_code(result)
    _print_reap_result(result)
    return _exit_code(result)


def _print_disk_report(report: DiskFootprintReport) -> None:
    console = Console()
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("OWNER")
    table.add_column("SECTION")
    table.add_column("SIZE", justify="right")
    table.add_column("HORIZON")
    table.add_column("PATH")
    for row in report.rows:
        owner = row.owner
        style = None
        if row.status == "unowned":
            owner = "unowned"
            style = "red"
        elif row.size_bytes >= 10 * 1024**3:
            style = "yellow"
        table.add_row(
            owner,
            row.section,
            format_bytes(row.size_bytes),
            row.horizon,
            row.path,
            style=style,
        )
    if not report.rows:
        table.add_row("[dim]none[/dim]", "-", "-", "-", "-")
    console.print(table)
    console.print(
        f"[dim]total listed: {format_bytes(report.total_bytes)}"
        f"; stray scan visited {report.stray_scan_visited} dirs"
        f"{' (truncated)' if report.stray_scan_truncated else ''}[/dim]"
    )
    for diagnostic in report.scan_diagnostics:
        console.print(f"[yellow]partial scan: {diagnostic}[/yellow]")


def _print_reap_result(result: DiskReapResult) -> None:
    console = Console()
    title = "Applied owner cleanups" if result.apply else "Dry-run owner cleanup plan"
    table = Table(title=title, show_header=True, header_style="bold", box=None)
    table.add_column("OWNER")
    table.add_column("MODE")
    table.add_column("RECLAIMABLE", justify="right")
    table.add_column("SUMMARY")
    for step in result.steps:
        style = "red" if step.mode in {"blocked", "error"} else None
        table.add_row(
            step.owner,
            step.mode,
            format_bytes(step.reclaimed_bytes),
            step.summary,
            style=style,
        )
    console.print(table)
    if result.apply:
        console.print(
            f"[green]Reclaimed estimate: {format_bytes(result.reclaimed_bytes)}[/green]"
        )
    else:
        console.print(
            "[cyan]Dry run only; pass --apply to run owner cleanup passes.[/cyan]"
        )


def _exit_code(result: DiskReapResult) -> int:
    return 1 if any(step.mode in {"blocked", "error"} for step in result.steps) else 0


__all__ = ["handle_disk_command"]
