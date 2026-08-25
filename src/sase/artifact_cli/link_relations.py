"""``sase artifact link relation list`` and ``show``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from rich.console import Console
from rich.table import Table

from sase.sdd.artifact_link_store import assembled_artifact_relations


def handle_link_relation(args: argparse.Namespace) -> int:
    """Dispatch one parsed ``sase artifact link relation`` subcommand."""

    handlers = {
        "list": _handle_link_relation_list,
        "show": _handle_link_relation_show,
    }
    subcommand = getattr(args, "relation_subcommand", None)
    handler = handlers.get(subcommand) if isinstance(subcommand, str) else None
    if handler is None:
        print("Usage: sase artifact link relation {list,show}", file=sys.stderr)
        return 2
    return handler(args)


def _handle_link_relation_list(args: argparse.Namespace) -> int:
    """List every relation in the closed registry."""

    relations = assembled_artifact_relations()
    if bool(getattr(args, "json", False)):
        json.dump(relations, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    _print_relation_table(relations)
    return 0


def _handle_link_relation_show(args: argparse.Namespace) -> int:
    """Show one relation's direction, worked examples, and recommended kinds."""

    relation = _lookup_relation(str(args.slug))
    if relation is None:
        print(f"Error: unknown relation: {args.slug}", file=sys.stderr)
        return 1
    if bool(getattr(args, "json", False)):
        json.dump(relation, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    _print_relation_detail(relation)
    return 0


def _print_relation_table(relations: list[dict[str, Any]]) -> None:
    console = Console()
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("SLUG", no_wrap=True, style="bold")
    table.add_column("INVERSE", no_wrap=True)
    table.add_column("DIRECTED", no_wrap=True)
    table.add_column("WRITTEN BY", no_wrap=True)
    table.add_column("DIRECTION")
    for relation in relations:
        table.add_row(
            str(relation.get("slug") or "-"),
            str(relation.get("inverse") or "-"),
            "yes" if relation.get("directed") else "no",
            str(relation.get("written_by") or "-"),
            str(relation.get("direction_note") or "-"),
        )
    console.print(table)


def _print_relation_detail(relation: dict[str, Any]) -> None:
    console = Console()
    console.print(
        f"[bold]{relation.get('slug')}[/bold] "
        f"(inverse: {relation.get('inverse')}, "
        f"directed: {'yes' if relation.get('directed') else 'no'}, "
        f"written by: {relation.get('written_by')})"
    )
    console.print(str(relation.get("direction_note") or ""))
    console.print(f"  + {relation.get('positive_example')}")
    console.print(f"  - {relation.get('negative_example')}")
    source_kinds = ", ".join(relation.get("recommended_source_kinds") or []) or "any"
    target_kinds = ", ".join(relation.get("recommended_target_kinds") or []) or "any"
    console.print(f"Recommended source kinds: {source_kinds}")
    console.print(f"Recommended target kinds: {target_kinds}")


def _lookup_relation(slug: str) -> dict[str, Any] | None:
    return next(
        (
            dict(relation)
            for relation in assembled_artifact_relations()
            if relation.get("slug") == slug
        ),
        None,
    )


__all__ = ["handle_link_relation"]
