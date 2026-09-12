"""List handler for ``sase monitor``."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console

from sase.monitor import list_monitors

from ..monitor_render import (
    empty_monitor_panel,
    monitor_list_json,
    monitor_list_markdown,
    monitor_table,
)


def handle_monitor_list(args: argparse.Namespace) -> int:
    """Render monitor family members as a table, markdown, or JSON."""
    project = getattr(args, "project", None)
    agent = getattr(args, "agent", None)
    statuses = set(getattr(args, "status", None) or ())
    include_all = bool(getattr(args, "all", False))
    limit = getattr(args, "limit", None)
    fmt = (
        "json"
        if bool(getattr(args, "json", False))
        else getattr(args, "format", "table")
    )

    try:
        records = list_monitors(project=project)
    except Exception as exc:
        print(f"sase monitor list: cannot read monitors: {exc}", file=sys.stderr)
        return 1

    if agent:
        records = [record for record in records if record.lane == agent]
    if statuses:
        records = [record for record in records if record.monitor_state in statuses]
    elif not include_all:
        records = [record for record in records if not record.is_terminal]
    if limit is not None:
        records = records[: max(0, limit)]

    if fmt == "json":
        scope = {
            "all": include_all,
            "project": project,
            "agent": agent,
            "lane": agent,  # deprecated alias for "agent", kept for compatibility
            "status": sorted(statuses) or None,
        }
        json.dump(monitor_list_json(records, scope=scope), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    if fmt == "markdown":
        sys.stdout.write(monitor_list_markdown(records))
        return 0

    console = Console()
    title = (
        f"Monitors · {_scope_label(project=project, agent=agent, include_all=include_all)} "
        f"({len(records)})"
    )
    if records:
        console.print(monitor_table(records, title=title))
    else:
        hint = (
            None
            if include_all
            else "No active monitors; pass -a/--all to include finished ones."
        )
        console.print(empty_monitor_panel(title, hint=hint))
    return 0


def _scope_label(*, project: str | None, agent: str | None, include_all: bool) -> str:
    parts = ["all projects" if project is None else f"project {project}"]
    if agent:
        parts.append(f"agent {agent}")
    parts.append("all" if include_all else "active")
    return ", ".join(parts)


__all__ = [
    "handle_monitor_list",
]
