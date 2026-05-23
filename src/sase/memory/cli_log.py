"""Rich and JSON rendering for ``sase memory log`` summaries."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.main.init_memory.config import project_memory_name
from sase.memory.read_log import (
    MemoryReadEvent,
    filter_memory_read_events,
    read_memory_read_events,
    summarize_memory_reads_by_path,
)

_REASON_PREVIEW_WIDTH = 72


def handle_memory_log_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Render or serialize the project-scoped memory-read summary."""
    root = Path.cwd()
    project_name = project_memory_name(root)
    events = read_memory_read_events(project=project_name)
    path_filter = getattr(args, "path", None)
    agent_filter = getattr(args, "agent", None)
    filtered_events = filter_memory_read_events(
        events,
        canonical_path=path_filter,
        agent_name=agent_filter,
    )

    if getattr(args, "json", False):
        payload = _build_memory_log_summary_payload(
            filtered_events,
            project_name=project_name,
            path_filter=path_filter,
            agent_filter=agent_filter,
        )
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return

    _render_memory_log_summary(
        filtered_events,
        console=console,
        project_name=project_name,
        path_filter=path_filter,
        agent_filter=agent_filter,
    )


def _render_memory_log_summary(
    events: Iterable[MemoryReadEvent],
    *,
    console: Console | None = None,
    project_name: str,
    path_filter: str | None = None,
    agent_filter: str | None = None,
) -> None:
    """Print the Rich summary dashboard for memory-read events."""
    event_tuple = tuple(events)
    target = console or Console()
    target.print(
        _build_memory_log_summary_dashboard(
            event_tuple,
            project_name=project_name,
            path_filter=path_filter,
            agent_filter=agent_filter,
        )
    )


def _build_memory_log_summary_payload(
    events: Iterable[MemoryReadEvent],
    *,
    project_name: str,
    path_filter: str | None = None,
    agent_filter: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic JSON payload for the summary view."""
    event_tuple = tuple(events)
    summaries = summarize_memory_reads_by_path(event_tuple)
    return {
        "filters": {
            "agent": _normalized_filter(agent_filter),
            "path": _normalized_filter(path_filter),
        },
        "project": project_name,
        "summary": [asdict(summary) for summary in summaries],
        "total_agents": len({event.agent_name for event in event_tuple}),
        "total_memory_paths": len({event.canonical_path for event in event_tuple}),
        "total_reads": len(event_tuple),
    }


def _build_memory_log_summary_dashboard(
    events: tuple[MemoryReadEvent, ...],
    *,
    project_name: str,
    path_filter: str | None = None,
    agent_filter: str | None = None,
) -> Group:
    """Build the static Rich dashboard for the memory-read summary."""
    return Group(
        _summary_panel(
            events,
            project_name=project_name,
            path_filter=path_filter,
            agent_filter=agent_filter,
        ),
        _paths_panel(
            events,
            path_filter=path_filter,
            agent_filter=agent_filter,
        ),
    )


def _summary_panel(
    events: tuple[MemoryReadEvent, ...],
    *,
    project_name: str,
    path_filter: str | None = None,
    agent_filter: str | None = None,
) -> Panel:
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Project", project_name)
    summary.add_row("Filters", _filter_label(path_filter, agent_filter))
    summary.add_row("Read events", str(len(events)))
    summary.add_row(
        "Memory paths", str(len({event.canonical_path for event in events}))
    )
    summary.add_row("Agents", str(len({event.agent_name for event in events})))
    return Panel(summary, title="SASE Memory Read Log", border_style="cyan")


def _paths_panel(
    events: tuple[MemoryReadEvent, ...],
    *,
    path_filter: str | None = None,
    agent_filter: str | None = None,
) -> Panel:
    summaries = summarize_memory_reads_by_path(events)
    if not summaries:
        message = (
            "No memory read events match the current filters."
            if _filter_label(path_filter, agent_filter) != "none"
            else "No memory read events found."
        )
        return Panel(
            Text(message, style="dim"),
            title="Memory Paths (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Memory path")
    table.add_column("Reads", justify="right", no_wrap=True)
    table.add_column("Agents", justify="right", no_wrap=True)
    table.add_column("Last read", no_wrap=True)
    table.add_column("Last agent", no_wrap=True)
    table.add_column("Last reason")

    for summary in summaries:
        table.add_row(
            summary.canonical_path,
            str(summary.read_count),
            str(summary.distinct_agent_count),
            summary.last_read_at,
            summary.last_agent,
            _reason_preview(summary.last_reason),
        )

    return Panel(
        table,
        title=f"Memory Paths ({len(summaries)})",
        border_style="cyan",
    )


def _filter_label(path_filter: str | None, agent_filter: str | None) -> str:
    parts: list[str] = []
    path = _normalized_filter(path_filter)
    agent = _normalized_filter(agent_filter)
    if path is not None:
        parts.append(f"path={path}")
    if agent is not None:
        parts.append(f"agent={agent}")
    return ", ".join(parts) if parts else "none"


def _normalized_filter(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _reason_preview(reason: str) -> str:
    one_line = " ".join(reason.split())
    if len(one_line) <= _REASON_PREVIEW_WIDTH:
        return one_line
    return one_line[: _REASON_PREVIEW_WIDTH - 3].rstrip() + "..."
