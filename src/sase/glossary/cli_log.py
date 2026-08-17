"""Rich and JSON rendering for ``sase glossary log`` summaries."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import asdict
import json
import sys
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.core.time import format_local
from sase.glossary.cli_common import (
    GlossaryCliError,
    resolve_glossary_cli_project_name,
)
from sase.glossary.read_log import (
    GlossaryReadAgentSummary,
    GlossaryReadEvent,
    GlossaryReadTermSummary,
    filter_glossary_read_events,
    glossary_read_log_path,
    read_glossary_read_events,
    summarize_glossary_reads_by_agent,
    summarize_glossary_reads_by_term,
)

_REASON_PREVIEW_WIDTH = 72
_ID_ERROR_MATCH_LIMIT = 5


class _GlossaryLogLookupError(ValueError):
    """Raised when a requested glossary-read event cannot be selected."""


def handle_glossary_log_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Render or serialize the project-scoped glossary-read summary."""
    try:
        project_name = resolve_glossary_cli_project_name(getattr(args, "project", None))
    except GlossaryCliError as exc:
        print(f"sase glossary log: {exc}", file=sys.stderr)
        sys.exit(1)

    events = read_glossary_read_events(log_path=glossary_read_log_path(project_name))
    term_filter = getattr(args, "term", None)
    agent_filter = getattr(args, "agent", None)
    read_id = getattr(args, "id", None)
    filtered_events = filter_glossary_read_events(
        events,
        term=term_filter,
        agent_name=agent_filter,
    )
    as_json = getattr(args, "format", "table") == "json"

    if _normalized_filter(read_id) is not None:
        try:
            event = _select_glossary_read_event(filtered_events, read_id)
        except _GlossaryLogLookupError as exc:
            print(f"sase glossary log: {exc}", file=sys.stderr)
            sys.exit(1)

        if as_json:
            json.dump(asdict(event), sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return

        _render_glossary_log_event(
            event,
            console=console,
            project_name=project_name,
            term_filter=term_filter,
            agent_filter=agent_filter,
        )
        return

    if as_json:
        payload = _build_glossary_log_summary_payload(
            filtered_events,
            project_name=project_name,
            term_filter=term_filter,
            agent_filter=agent_filter,
        )
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return

    if not filtered_events:
        print(_empty_state_message(term_filter=term_filter, agent_filter=agent_filter))
        return

    _render_glossary_log_summary(
        filtered_events,
        console=console,
        project_name=project_name,
        term_filter=term_filter,
        agent_filter=agent_filter,
    )


def _render_glossary_log_summary(
    events: Iterable[GlossaryReadEvent],
    *,
    console: Console | None = None,
    project_name: str,
    term_filter: str | None = None,
    agent_filter: str | None = None,
) -> None:
    """Print the Rich summary dashboard for glossary-read events."""
    target = console or Console()
    target.print(
        _build_glossary_log_summary_dashboard(
            tuple(events),
            project_name=project_name,
            term_filter=term_filter,
            agent_filter=agent_filter,
        )
    )


def _build_glossary_log_summary_payload(
    events: Iterable[GlossaryReadEvent],
    *,
    project_name: str,
    term_filter: str | None = None,
    agent_filter: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic JSON payload for the summary view."""
    event_tuple = _ordered_events(events)
    latest = event_tuple[0] if event_tuple else None
    requested_terms = {term for event in event_tuple for term in event.terms}
    return {
        "by_agent": [
            asdict(summary)
            for summary in summarize_glossary_reads_by_agent(event_tuple)
        ],
        "by_term": [
            asdict(summary) for summary in summarize_glossary_reads_by_term(event_tuple)
        ],
        "definition_bytes": sum(event.definition_bytes for event in event_tuple),
        "distinct_agents": len({event.agent_name for event in event_tuple}),
        "distinct_requested_terms": len(requested_terms),
        "events": [asdict(event) for event in event_tuple],
        "filters": {
            "agent": _normalized_filter(agent_filter),
            "term": _normalized_filter(term_filter),
        },
        "most_recent_agent": None if latest is None else latest.agent_name,
        "most_recent_read_at": None if latest is None else latest.timestamp,
        "most_recent_reason": None if latest is None else latest.reason,
        "project": project_name,
        "total_reads": len(event_tuple),
    }


def _build_glossary_log_summary_dashboard(
    events: tuple[GlossaryReadEvent, ...],
    *,
    project_name: str,
    term_filter: str | None = None,
    agent_filter: str | None = None,
) -> Group:
    """Build the static Rich dashboard for the glossary-read summary."""
    return Group(
        _summary_panel(
            events,
            project_name=project_name,
            term_filter=term_filter,
            agent_filter=agent_filter,
        ),
        _terms_panel(events),
        _agents_panel(events),
        _events_panel(events),
    )


def _summary_panel(
    events: tuple[GlossaryReadEvent, ...],
    *,
    project_name: str,
    term_filter: str | None = None,
    agent_filter: str | None = None,
) -> Panel:
    latest = _ordered_events(events)[0] if events else None
    requested_terms = {term for event in events for term in event.terms}
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Project", project_name)
    summary.add_row("Filters", _filter_label(term_filter, agent_filter))
    summary.add_row("Read events", str(len(events)))
    summary.add_row("Requested terms", str(len(requested_terms)))
    summary.add_row("Agents", str(len({event.agent_name for event in events})))
    summary.add_row(
        "Definition bytes",
        str(sum(event.definition_bytes for event in events)),
    )
    summary.add_row(
        "Most recent read",
        "none" if latest is None else format_local(latest.timestamp),
    )
    if latest is not None:
        summary.add_row("Most recent reason", latest.reason)
    return Panel(summary, title="SASE Glossary Read Log", border_style="cyan")


def _terms_panel(events: tuple[GlossaryReadEvent, ...]) -> Panel:
    summaries: tuple[GlossaryReadTermSummary, ...] = summarize_glossary_reads_by_term(
        events
    )
    if not summaries:
        return Panel(
            Text("No glossary terms match the current filters.", style="dim"),
            title="Terms (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Term")
    table.add_column("Reads", justify="right", no_wrap=True)
    table.add_column("Agents", justify="right", no_wrap=True)
    table.add_column("Last read", no_wrap=True)
    table.add_column("Last reason")

    for summary in summaries:
        table.add_row(
            summary.term,
            str(summary.read_count),
            str(summary.distinct_agent_count),
            format_local(summary.last_read_at),
            _reason_preview(summary.last_reason),
        )

    return Panel(table, title=f"Terms ({len(summaries)})", border_style="cyan")


def _agents_panel(events: tuple[GlossaryReadEvent, ...]) -> Panel:
    summaries: tuple[GlossaryReadAgentSummary, ...] = summarize_glossary_reads_by_agent(
        events
    )
    if not summaries:
        return Panel(
            Text("No agents match the current filters.", style="dim"),
            title="Agents (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Agent")
    table.add_column("Reads", justify="right", no_wrap=True)
    table.add_column("Terms", justify="right", no_wrap=True)
    table.add_column("Last read", no_wrap=True)
    table.add_column("Last term")
    table.add_column("Last reason")

    for summary in summaries:
        table.add_row(
            summary.agent_name,
            str(summary.read_count),
            str(summary.distinct_term_count),
            format_local(summary.last_read_at),
            summary.last_term,
            _reason_preview(summary.last_reason),
        )

    return Panel(table, title=f"Agents ({len(summaries)})", border_style="cyan")


def _events_panel(events: tuple[GlossaryReadEvent, ...]) -> Panel:
    if not events:
        return Panel(
            Text(
                "No individual glossary read events match the current filters.",
                style="dim",
            ),
            title="Glossary Read Events (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ID", no_wrap=True)
    table.add_column("Timestamp", no_wrap=True)
    table.add_column("Agent", no_wrap=True)
    table.add_column("Terms")
    table.add_column("Related", justify="right", no_wrap=True)
    table.add_column("Reason")

    for event in _ordered_events(events):
        table.add_row(
            event.id,
            format_local(event.timestamp),
            event.agent_name,
            ", ".join(event.terms),
            str(len(event.related_terms)),
            _reason_preview(event.reason),
        )

    return Panel(
        table,
        title=f"Glossary Read Events ({len(events)})",
        border_style="cyan",
    )


def _render_glossary_log_event(
    event: GlossaryReadEvent,
    *,
    console: Console | None = None,
    project_name: str,
    term_filter: str | None = None,
    agent_filter: str | None = None,
) -> None:
    """Print the Rich detail view for one glossary-read event."""
    target = console or Console()
    target.print(
        Group(
            _summary_panel(
                (event,),
                project_name=project_name,
                term_filter=term_filter,
                agent_filter=agent_filter,
            ),
            _event_panel(event),
        )
    )


def _event_panel(event: GlossaryReadEvent) -> Panel:
    depth = "unlimited" if event.depth_limit is None else str(event.depth_limit)
    detail = Table.grid(padding=(0, 2))
    detail.add_column(style="bold")
    detail.add_column()
    detail.add_row("ID", event.id)
    detail.add_row("Timestamp", format_local(event.timestamp))
    detail.add_row("Project", event.project)
    detail.add_row("Agent", event.agent_name)
    detail.add_row("Agent source", event.agent_source)
    detail.add_row("Reason", event.reason)
    detail.add_row("Requested terms", ", ".join(event.terms) or "none")
    detail.add_row("Related terms", ", ".join(event.related_terms) or "none")
    detail.add_row("Depth limit", depth)
    detail.add_row("Definition bytes", str(event.definition_bytes))
    detail.add_row("Source path", event.source_path or "none")
    detail.add_row("CWD", event.cwd)
    detail.add_row("Artifacts dir", event.artifacts_dir or "none")
    return Panel(detail, title=f"Glossary Read Event {event.id}", border_style="cyan")


def _select_glossary_read_event(
    events: tuple[GlossaryReadEvent, ...],
    read_id: str | None,
) -> GlossaryReadEvent:
    normalized = _normalized_filter(read_id)
    if normalized is None:
        raise _GlossaryLogLookupError("glossary read id must not be empty")

    exact_matches = tuple(event for event in events if event.id == normalized)
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise _GlossaryLogLookupError(f"glossary read id is not unique: {normalized}")

    prefix_matches = tuple(event for event in events if event.id.startswith(normalized))
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if not prefix_matches:
        raise _GlossaryLogLookupError(f"unknown glossary read id: {normalized}")

    matches = ", ".join(event.id for event in prefix_matches[:_ID_ERROR_MATCH_LIMIT])
    if len(prefix_matches) > _ID_ERROR_MATCH_LIMIT:
        matches += ", ..."
    raise _GlossaryLogLookupError(
        f"glossary read id prefix is ambiguous: {normalized} (matches: {matches})"
    )


def _empty_state_message(*, term_filter: str | None, agent_filter: str | None) -> str:
    label = _filter_label(term_filter, agent_filter)
    if label == "none":
        return "No glossary read events found."
    return f"No glossary read events match the current filters ({label})."


def _filter_label(term_filter: str | None, agent_filter: str | None) -> str:
    parts: list[str] = []
    term = _normalized_filter(term_filter)
    agent = _normalized_filter(agent_filter)
    if term is not None:
        parts.append(f"term={term}")
    if agent is not None:
        parts.append(f"agent={agent}")
    return ", ".join(parts) if parts else "none"


def _ordered_events(
    events: Iterable[GlossaryReadEvent],
) -> tuple[GlossaryReadEvent, ...]:
    return tuple(
        sorted(events, key=lambda event: (event.timestamp, event.id), reverse=True)
    )


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


__all__ = ["handle_glossary_log_command"]
