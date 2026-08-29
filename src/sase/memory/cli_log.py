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

from sase.core.time import format_local
from sase.memory.legacy_glossary_read_log import (
    GlossaryReadEvent,
    filter_glossary_read_events,
    read_glossary_read_events,
)
from sase.main.init_memory.config import project_memory_name
from sase.memory.read_log import (
    MemoryReadEvent,
    filter_memory_read_events,
    read_memory_read_events,
    summarize_memory_reads_by_agent,
    summarize_memory_reads_by_path,
)

_REASON_PREVIEW_WIDTH = 72
_ID_ERROR_MATCH_LIMIT = 5


class _MemoryLogLookupError(ValueError):
    """Raised when a requested memory read event cannot be selected."""


def handle_memory_log_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Render or serialize the project-scoped memory-read summary."""
    root = Path.cwd()
    project_name = project_memory_name(root)
    events = read_memory_read_events(project=project_name)
    path_filter = getattr(args, "path", None)
    agent_filter = getattr(args, "agent", None)
    read_id = getattr(args, "id", None)
    include_glossary = _include_glossary(args)
    filtered_events = filter_memory_read_events(
        events,
        canonical_path=path_filter,
        agent_name=agent_filter,
    )
    glossary_events = (
        filter_glossary_read_events(
            read_glossary_read_events(project=project_name),
            agent_name=agent_filter,
        )
        if include_glossary
        else None
    )

    if _normalized_filter(read_id) is not None:
        try:
            event = _select_memory_read_event(filtered_events, read_id)
        except _MemoryLogLookupError as exc:
            print(f"sase memory log: {exc}", file=sys.stderr)
            sys.exit(1)

        if getattr(args, "json", False):
            json.dump(asdict(event), sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return

        _render_memory_log_event(
            event,
            console=console,
            project_name=project_name,
            path_filter=path_filter,
            agent_filter=agent_filter,
        )
        return

    if getattr(args, "json", False):
        payload = _build_memory_log_summary_payload(
            filtered_events,
            project_name=project_name,
            path_filter=path_filter,
            agent_filter=agent_filter,
        )
        if glossary_events is not None:
            payload.update(_build_memory_log_glossary_payload(glossary_events))
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return

    _render_memory_log_summary(
        filtered_events,
        console=console,
        project_name=project_name,
        path_filter=path_filter,
        agent_filter=agent_filter,
        glossary_events=glossary_events,
    )


def _render_memory_log_summary(
    events: Iterable[MemoryReadEvent],
    *,
    console: Console | None = None,
    project_name: str,
    path_filter: str | None = None,
    agent_filter: str | None = None,
    glossary_events: tuple[GlossaryReadEvent, ...] | None = None,
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
            glossary_events=glossary_events,
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


def _build_memory_log_glossary_payload(
    events: Iterable[GlossaryReadEvent],
) -> dict[str, Any]:
    """Build deterministic legacy glossary-read audit data for inclusive views."""
    event_tuple = tuple(sorted(events, key=lambda event: (event.timestamp, event.id)))
    return {
        "glossary_events": [asdict(event) for event in event_tuple],
        "glossary_summary": {
            "total_events": len(event_tuple),
            "total_terms": len({term for event in event_tuple for term in event.terms}),
        },
    }


def _glossary_events_panel(events: tuple[GlossaryReadEvent, ...]) -> Panel:
    if not events:
        return Panel(
            Text(
                "No legacy glossary read events match the current filters.", style="dim"
            ),
            title="Glossary Read Events (0)",
            border_style="magenta",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Timestamp", no_wrap=True)
    table.add_column("Agent", no_wrap=True)
    table.add_column("Terms")
    table.add_column("Reason")

    ordered = sorted(
        events, key=lambda event: (event.timestamp, event.id), reverse=True
    )
    for event in ordered:
        table.add_row(
            format_local(event.timestamp),
            event.agent_name,
            ", ".join(event.terms),
            _reason_preview(event.reason),
        )

    return Panel(
        table,
        title=f"Glossary Read Events ({len(events)})",
        border_style="magenta",
    )


def _build_memory_log_summary_dashboard(
    events: tuple[MemoryReadEvent, ...],
    *,
    project_name: str,
    path_filter: str | None = None,
    agent_filter: str | None = None,
    glossary_events: tuple[GlossaryReadEvent, ...] | None = None,
) -> Group:
    """Build the static Rich dashboard for the memory-read summary."""
    panels: list[Panel] = [
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
    ]
    if _normalized_filter(agent_filter) is not None:
        panels.append(_agents_panel(events))
    if _is_drilldown(path_filter=path_filter, agent_filter=agent_filter):
        panels.append(_events_panel(events))
    if glossary_events is not None:
        panels.append(_glossary_events_panel(glossary_events))
    return Group(*panels)


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
            format_local(summary.last_read_at),
            summary.last_agent,
            _reason_preview(summary.last_reason),
        )

    return Panel(
        table,
        title=f"Memory Paths ({len(summaries)})",
        border_style="cyan",
    )


def _agents_panel(events: tuple[MemoryReadEvent, ...]) -> Panel:
    summaries = summarize_memory_reads_by_agent(events)
    if not summaries:
        return Panel(
            Text("No agents match the current filters.", style="dim"),
            title="Agents (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Agent")
    table.add_column("Reads", justify="right", no_wrap=True)
    table.add_column("Paths", justify="right", no_wrap=True)
    table.add_column("Last read", no_wrap=True)
    table.add_column("Last path")
    table.add_column("Last reason")

    for summary in summaries:
        table.add_row(
            summary.agent_name,
            str(summary.read_count),
            str(summary.distinct_path_count),
            format_local(summary.last_read_at),
            summary.last_path,
            _reason_preview(summary.last_reason),
        )

    return Panel(
        table,
        title=f"Agents ({len(summaries)})",
        border_style="cyan",
    )


def _events_panel(events: tuple[MemoryReadEvent, ...]) -> Panel:
    if not events:
        return Panel(
            Text(
                "No individual memory read events match the current filters.",
                style="dim",
            ),
            title="Memory Read Events (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ID", no_wrap=True)
    table.add_column("Timestamp", no_wrap=True)
    table.add_column("Agent", no_wrap=True)
    table.add_column("Memory path")
    table.add_column("Reason")

    ordered_events = sorted(
        events,
        key=lambda event: (event.timestamp, event.id),
        reverse=True,
    )
    for event in ordered_events:
        table.add_row(
            event.id,
            format_local(event.timestamp),
            event.agent_name,
            event.canonical_path,
            _reason_preview(event.reason),
        )

    return Panel(
        table,
        title=f"Memory Read Events ({len(events)})",
        border_style="cyan",
    )


def _render_memory_log_event(
    event: MemoryReadEvent,
    *,
    console: Console | None = None,
    project_name: str,
    path_filter: str | None = None,
    agent_filter: str | None = None,
) -> None:
    """Print the Rich detail view for one memory-read event."""
    target = console or Console()
    target.print(
        _build_memory_log_event_dashboard(
            event,
            project_name=project_name,
            path_filter=path_filter,
            agent_filter=agent_filter,
        )
    )


def _build_memory_log_event_dashboard(
    event: MemoryReadEvent,
    *,
    project_name: str,
    path_filter: str | None = None,
    agent_filter: str | None = None,
) -> Group:
    return Group(
        _summary_panel(
            (event,),
            project_name=project_name,
            path_filter=path_filter,
            agent_filter=agent_filter,
        ),
        _event_panel(event),
    )


def _event_panel(event: MemoryReadEvent) -> Panel:
    detail = Table.grid(padding=(0, 2))
    detail.add_column(style="bold")
    detail.add_column()
    detail.add_row("ID", event.id)
    detail.add_row("Timestamp", format_local(event.timestamp))
    detail.add_row("Project", event.project)
    detail.add_row("Memory path", event.canonical_path)
    detail.add_row("Resolved path", event.resolved_path)
    detail.add_row("Agent", event.agent_name)
    detail.add_row("Agent source", event.agent_source)
    detail.add_row("Reason", event.reason)
    detail.add_row("CWD", event.cwd)
    detail.add_row("Artifacts dir", event.artifacts_dir or "none")
    detail.add_row("Byte count", str(event.byte_count))
    detail.add_row("Frontmatter stripped", str(event.frontmatter_stripped).lower())
    return Panel(detail, title=f"Memory Read Event {event.id}", border_style="cyan")


def _filter_label(path_filter: str | None, agent_filter: str | None) -> str:
    parts: list[str] = []
    path = _normalized_filter(path_filter)
    agent = _normalized_filter(agent_filter)
    if path is not None:
        parts.append(f"path={path}")
    if agent is not None:
        parts.append(f"agent={agent}")
    return ", ".join(parts) if parts else "none"


def _is_drilldown(*, path_filter: str | None, agent_filter: str | None) -> bool:
    return (
        _normalized_filter(path_filter) is not None
        or _normalized_filter(agent_filter) is not None
    )


def _select_memory_read_event(
    events: tuple[MemoryReadEvent, ...],
    read_id: str | None,
) -> MemoryReadEvent:
    normalized = _normalized_filter(read_id)
    if normalized is None:
        raise _MemoryLogLookupError("memory read id must not be empty")

    exact_matches = tuple(event for event in events if event.id == normalized)
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise _MemoryLogLookupError(f"memory read id is not unique: {normalized}")

    prefix_matches = tuple(event for event in events if event.id.startswith(normalized))
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if not prefix_matches:
        raise _MemoryLogLookupError(f"unknown memory read id: {normalized}")

    matches = ", ".join(event.id for event in prefix_matches[:_ID_ERROR_MATCH_LIMIT])
    if len(prefix_matches) > _ID_ERROR_MATCH_LIMIT:
        matches += ", ..."
    raise _MemoryLogLookupError(
        f"memory read id prefix is ambiguous: {normalized} (matches: {matches})"
    )


def _include_glossary(args: argparse.Namespace) -> bool:
    return "glossary" in (getattr(args, "include", None) or ())


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
