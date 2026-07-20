"""``sase telemetry cleanup-test-data`` explicit maintenance action."""

from __future__ import annotations

import argparse
from typing import Any

from rich.console import Console
from rich.table import Table

from sase.telemetry.maintenance import (
    TEST_DATA_LABEL_MATCHES,
    cleanup_test_data,
)
from sase.telemetry.render import format_bytes


def handle_telemetry_cleanup_test_data(args: argparse.Namespace) -> None:
    """Preview exact test-label matches and delete only with ``--yes``."""
    console = Console()
    providers = " or ".join(TEST_DATA_LABEL_MATCHES["llm_provider"])
    workflow = TEST_DATA_LABEL_MATCHES["workflow"][0]
    console.print(
        "[bold]Exact cleanup criteria[/bold]: "
        f"[cyan]llm_provider[/cyan] = [magenta]{providers}[/magenta]; "
        f"[cyan]workflow[/cyan] = [magenta]{workflow}[/magenta]"
    )
    preview = cleanup_test_data(dry_run=True)
    _render_report(console, preview, heading="Preview")

    if args.dry_run:
        console.print("[yellow]Dry run only; no telemetry rows were changed.[/yellow]")
        return
    if not args.yes:
        console.print(
            "[red]Refusing deletion without explicit -y/--yes.[/red] "
            "Review the preview, then rerun with --yes."
        )
        raise SystemExit(2)

    report = cleanup_test_data(dry_run=False)
    _render_report(console, report, heading="Deleted")
    if report.get("total_rows", 0):
        console.print(
            "[green]Cleanup complete.[/green] Space reclaimed: "
            f"[bold]{format_bytes(int(report.get('reclaimed_bytes', 0)))}[/bold]."
        )
    else:
        console.print("[green]No matching test telemetry remained.[/green]")


def _render_report(
    console: Console,
    report: dict[str, Any],
    *,
    heading: str,
) -> None:
    table = Table(title=f"{heading} test-labeled telemetry")
    table.add_column("Raw", justify="right", style="cyan")
    table.add_column("5-minute", justify="right", style="blue")
    table.add_column("1-hour", justify="right", style="magenta")
    table.add_column("Total", justify="right", style="bold")
    table.add_row(
        str(report.get("raw_rows", 0)),
        str(report.get("rollup_5m_rows", 0)),
        str(report.get("rollup_1h_rows", 0)),
        str(report.get("total_rows", 0)),
    )
    console.print(table)
    before = int(report.get("store_size_before_bytes", 0))
    after = int(report.get("store_size_after_bytes", before))
    console.print(
        f"[dim]Store size: {format_bytes(before)} → {format_bytes(after)}[/dim]"
    )


__all__ = [
    "TEST_DATA_LABEL_MATCHES",
    "handle_telemetry_cleanup_test_data",
]
