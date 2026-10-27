"""Dispatch for the ``sase footprint`` command group."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from rich.console import Console
from rich.table import Table

from sase.footprint.catalog import CatalogEntry, load_catalog
from sase.main.parser import create_parser
from sase.main.parser_root_help import root_subparser_action


def handle_footprint_command(args: argparse.Namespace) -> int:
    """Handle ``sase footprint`` and its implemented subcommands."""
    subcommand = getattr(args, "footprint_subcommand", None)
    if subcommand is None:
        _print_group_help()
        return 0
    if subcommand == "catalog":
        return _handle_catalog(args)
    print(
        f"sase footprint: unknown view {subcommand!r}. Implemented views: catalog.",
        file=sys.stderr,
    )
    return 2


def _print_group_help() -> None:
    parser = create_parser(only="footprint")
    root_subparser_action(parser).choices["footprint"].print_help()


def _handle_catalog(args: argparse.Namespace) -> int:
    header, entries = load_catalog()
    area = getattr(args, "area", None)
    namespace = getattr(args, "namespace", None)
    fmt = getattr(args, "format", None) or "rich"
    if area is not None:
        entries = [entry for entry in entries if entry.area == area]
    if namespace is not None:
        entries = [entry for entry in entries if entry.ns == namespace]
    if fmt == "json":
        print(
            json.dumps(
                {
                    "schema": header.schema,
                    "rev": header.rev,
                    "count": len(entries),
                    "entries": [
                        {
                            "id": entry.id,
                            "ns": entry.ns,
                            "area": entry.area,
                            "kind": entry.kind,
                            "label": entry.label,
                            "parent": entry.parent,
                            "src": entry.src,
                        }
                        for entry in entries
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if fmt == "markdown":
        _print_catalog_markdown(header.rev, entries)
        return 0
    _print_catalog_rich(header.rev, entries)
    return 0


def _print_catalog_rich(rev: str, entries: list[CatalogEntry]) -> None:
    counts = Counter(entry.area for entry in entries)
    console = Console()
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("AREA")
    table.add_column("FEATURES", justify="right")
    for area in sorted(counts):
        table.add_row(area, str(counts[area]))
    console.print(table)
    console.print(
        f"{len(entries)} features · catalog rev {rev}",
        style="dim",
    )


def _print_catalog_markdown(rev: str, entries: list[CatalogEntry]) -> None:
    print(f"# Footprint catalog (rev {rev})")
    print()
    for area in sorted({entry.area for entry in entries}):
        print(f"## {area}")
        print()
        for entry in [entry for entry in entries if entry.area == area]:
            print(f"- `{entry.id}` — {entry.label}")
        print()


__all__ = ["handle_footprint_command"]
