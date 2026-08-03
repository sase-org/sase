"""Implementation of ``sase artifact list``."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.artifact_cli.references import artifact_file_json_dict
from sase.core.artifact_file_query_facade import query_artifact_files
from sase.core.artifact_file_types import ArtifactFile
from sase.core.time import format_local
from sase.project_display_names import (
    ProjectRefDisplaySnapshot,
    load_project_ref_display_snapshot,
)


_CREATED_COLUMN_WIDTH = 16


def handle_list(args: argparse.Namespace) -> int:
    """Query and render indexed artifacts."""

    projects = load_project_ref_display_snapshot()
    project = _resolve_project_filter(getattr(args, "project", None), projects)
    if getattr(args, "project", None) is not None and project is None:
        print(
            f"Error: unknown project reference: {args.project}",
            file=sys.stderr,
        )
        return 2

    rows = query_artifact_files(
        kinds=getattr(args, "kind", None),
        project=project,
        agent=getattr(args, "agent", None),
        since=getattr(args, "since", None),
        explicit_only=bool(getattr(args, "explicit", False)),
        unused_only=bool(getattr(args, "unused", False)),
        query=getattr(args, "query", None),
        limit=getattr(args, "limit", 50),
    )
    if bool(getattr(args, "json", False)):
        json.dump(
            [artifact_file_json_dict(artifact_file) for artifact_file in rows],
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return 0

    _print_pretty(
        rows,
        projects,
        unused_only=bool(getattr(args, "unused", False)),
    )
    return 0


def _resolve_project_filter(
    raw: str | None,
    projects: ProjectRefDisplaySnapshot,
) -> str | None:
    if raw is None:
        return None
    return projects.project_key_for_ref(raw)


def _print_pretty(
    rows: list[ArtifactFile],
    projects: ProjectRefDisplaySnapshot,
    *,
    unused_only: bool = False,
) -> None:
    console = Console()
    title = f"Artifacts ({len(rows)}{', unused' if unused_only else ''})"
    if not rows:
        console.print(
            Panel(
                Text.from_markup("[dim]No artifacts found.[/dim]"),
                title=title,
                border_style="cyan",
            )
        )
        return

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("KIND", no_wrap=True)
    table.add_column("REF", style="bold")
    table.add_column("LABEL")
    table.add_column("PROJECT")
    table.add_column("AGENT")
    table.add_column("SIZE", justify="right", no_wrap=True)
    table.add_column(
        "CREATED",
        no_wrap=True,
        width=_CREATED_COLUMN_WIDTH,
    )
    for artifact_file in rows:
        table.add_row(
            artifact_file.kind,
            f"file:{artifact_file.id}",
            artifact_file.label,
            (
                projects.display_snapshot.label_for(artifact_file.project)
                if artifact_file.project
                else "-"
            ),
            artifact_file.agent_name or "-",
            _human_size(artifact_file.size_bytes),
            _minute_precision(artifact_file.created_at),
        )
    console.print(Panel(table, title=title, border_style="cyan"))


def _human_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "-"
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


def _minute_precision(created_at: str | None) -> str:
    return format_local(created_at, "%Y-%m-%d %H:%M", default="-")


__all__ = ["handle_list"]
