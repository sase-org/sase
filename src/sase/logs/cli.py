"""CLI handler for the ``sase logs`` command."""

import argparse
import sys
from typing import NoReturn

from rich.console import Console

from sase.logs.daterange import parse_daterange
from sase.logs.pack import build_pack


def handle_logs_command(args: argparse.Namespace) -> NoReturn:
    """Handle the ``sase logs <daterange>`` command."""
    console = Console()
    range_spec: str = args.daterange

    try:
        start, end = parse_daterange(range_spec)
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)

    console.print(
        f"[bold]Collecting logs[/bold] from "
        f"[cyan]{start.strftime('%Y-%m-%d %H:%M')}[/cyan] to "
        f"[cyan]{end.strftime('%Y-%m-%d %H:%M')}[/cyan]"
    )

    pack_dir = build_pack(start, end, range_spec)

    console.print(f"\n[bold green]Pack created:[/bold green] {pack_dir}")
    sys.exit(0)
