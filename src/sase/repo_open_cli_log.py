"""Rich and JSON rendering for ``sase repo log`` audit events."""

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

from sase.repo_open_log import (
    RepoOpenEvent,
    filter_repo_open_events,
    read_repo_open_events,
    summarize_repo_opens_by_agent,
    summarize_repo_opens_by_repo,
)

_REASON_PREVIEW_WIDTH = 72
_ID_ERROR_MATCH_LIMIT = 5
_KIND_STYLES = {
    "primary": "bold #00D7AF",
    "sidecar": "bold #AF87FF",
    "linked": "bold #87D7FF",
}


class _RepoOpenLogLookupError(ValueError):
    """Raised when a requested repository-open event cannot be selected."""


def handle_repo_log_command(
    args: argparse.Namespace,
    *,
    project_name: str,
    log_project_name: str | None = None,
    console: Console | None = None,
) -> int:
    """Render or serialize one project's repository-open audit log."""

    repo_filter = _normalized_filter(getattr(args, "repo", None))
    agent_filter = _normalized_filter(getattr(args, "agent", None))
    workspace_filter = getattr(args, "workspace", None)
    if workspace_filter is not None and workspace_filter < 0:
        print(
            f"sase repo log: workspace number must be >= 0, got {workspace_filter}",
            file=sys.stderr,
        )
        return 2

    events = read_repo_open_events(project=log_project_name or project_name)
    filtered_events = filter_repo_open_events(
        events,
        repo=repo_filter,
        agent_name=agent_filter,
        workspace_num=workspace_filter,
    )
    open_id = getattr(args, "id", None)
    if open_id is not None:
        try:
            event = _select_repo_open_event(filtered_events, open_id)
        except _RepoOpenLogLookupError as exc:
            print(f"sase repo log: {exc}", file=sys.stderr)
            return 1

        if getattr(args, "json", False):
            json.dump(asdict(event), sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return 0

        _render_repo_open_log_event(
            event,
            console=console,
            project_name=project_name,
            repo_filter=repo_filter,
            agent_filter=agent_filter,
            workspace_filter=workspace_filter,
        )
        return 0

    if getattr(args, "json", False):
        payload = _build_repo_open_log_summary_payload(
            filtered_events,
            project_name=project_name,
            repo_filter=repo_filter,
            agent_filter=agent_filter,
            workspace_filter=workspace_filter,
        )
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    _render_repo_open_log_summary(
        filtered_events,
        console=console,
        project_name=project_name,
        repo_filter=repo_filter,
        agent_filter=agent_filter,
        workspace_filter=workspace_filter,
    )
    return 0


def _render_repo_open_log_summary(
    events: Iterable[RepoOpenEvent],
    *,
    console: Console | None = None,
    project_name: str,
    repo_filter: str | None = None,
    agent_filter: str | None = None,
    workspace_filter: int | None = None,
) -> None:
    """Print the Rich summary dashboard for repository-open events."""

    event_tuple = tuple(events)
    target = console or Console()
    target.print(
        _build_repo_open_log_summary_dashboard(
            event_tuple,
            project_name=project_name,
            repo_filter=repo_filter,
            agent_filter=agent_filter,
            workspace_filter=workspace_filter,
        )
    )


def _build_repo_open_log_summary_payload(
    events: Iterable[RepoOpenEvent],
    *,
    project_name: str,
    repo_filter: str | None = None,
    agent_filter: str | None = None,
    workspace_filter: int | None = None,
) -> dict[str, Any]:
    """Build a deterministic JSON payload for the summary view."""

    event_tuple = tuple(events)
    summaries = summarize_repo_opens_by_repo(event_tuple)
    return {
        "filters": {
            "agent": _normalized_filter(agent_filter),
            "repo": _normalized_filter(repo_filter),
            "workspace": workspace_filter,
        },
        "project": project_name,
        "summary": [asdict(summary) for summary in summaries],
        "total_agents": len({event.agent_name for event in event_tuple}),
        "total_open_events": len(event_tuple),
        "total_repos": len({(event.repo, event.repo_kind) for event in event_tuple}),
    }


def _build_repo_open_log_summary_dashboard(
    events: tuple[RepoOpenEvent, ...],
    *,
    project_name: str,
    repo_filter: str | None = None,
    agent_filter: str | None = None,
    workspace_filter: int | None = None,
) -> Group:
    """Build the static Rich dashboard for repository-open events."""

    panels: list[Panel] = [
        _summary_panel(
            events,
            project_name=project_name,
            repo_filter=repo_filter,
            agent_filter=agent_filter,
            workspace_filter=workspace_filter,
        ),
        _repos_panel(
            events,
            repo_filter=repo_filter,
            agent_filter=agent_filter,
            workspace_filter=workspace_filter,
        ),
    ]
    if _is_drilldown(
        repo_filter=repo_filter,
        agent_filter=agent_filter,
        workspace_filter=workspace_filter,
    ):
        panels.append(_agents_panel(events))
        panels.append(_events_panel(events))
    return Group(*panels)


def _summary_panel(
    events: tuple[RepoOpenEvent, ...],
    *,
    project_name: str,
    repo_filter: str | None = None,
    agent_filter: str | None = None,
    workspace_filter: int | None = None,
) -> Panel:
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Project", project_name)
    summary.add_row(
        "Filters",
        _filter_label(repo_filter, agent_filter, workspace_filter),
    )
    summary.add_row("Open events", str(len(events)))
    summary.add_row(
        "Repos",
        str(len({(event.repo, event.repo_kind) for event in events})),
    )
    summary.add_row("Agents", str(len({event.agent_name for event in events})))
    return Panel(summary, title="SASE Repo Open Log", border_style="cyan")


def _repos_panel(
    events: tuple[RepoOpenEvent, ...],
    *,
    repo_filter: str | None = None,
    agent_filter: str | None = None,
    workspace_filter: int | None = None,
) -> Panel:
    summaries = summarize_repo_opens_by_repo(events)
    if not summaries:
        message = (
            "No repository open events match the current filters."
            if _is_drilldown(
                repo_filter=repo_filter,
                agent_filter=agent_filter,
                workspace_filter=workspace_filter,
            )
            else "No repository open events found."
        )
        return Panel(
            Text(message, style="dim"),
            title="Repos (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Repo")
    table.add_column("Kind", no_wrap=True)
    table.add_column("Opens", justify="right", no_wrap=True)
    table.add_column("Agents", justify="right", no_wrap=True)
    table.add_column("Last opened", no_wrap=True)
    table.add_column("Last agent", no_wrap=True)
    table.add_column("Last reason")

    for summary in summaries:
        table.add_row(
            summary.repo,
            Text(summary.repo_kind, style=_KIND_STYLES[summary.repo_kind]),
            str(summary.open_count),
            str(summary.distinct_agent_count),
            summary.last_opened_at,
            summary.last_agent,
            _reason_preview(summary.last_reason),
        )

    return Panel(
        table,
        title=f"Repos ({len(summaries)})",
        border_style="cyan",
    )


def _agents_panel(events: tuple[RepoOpenEvent, ...]) -> Panel:
    summaries = summarize_repo_opens_by_agent(events)
    if not summaries:
        return Panel(
            Text("No agents match the current filters.", style="dim"),
            title="Agents (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Agent")
    table.add_column("Opens", justify="right", no_wrap=True)
    table.add_column("Repos", justify="right", no_wrap=True)
    table.add_column("Last opened", no_wrap=True)
    table.add_column("Last repo")
    table.add_column("Last reason")

    for summary in summaries:
        table.add_row(
            summary.agent_name,
            str(summary.open_count),
            str(summary.distinct_repo_count),
            summary.last_opened_at,
            summary.last_repo,
            _reason_preview(summary.last_reason),
        )

    return Panel(
        table,
        title=f"Agents ({len(summaries)})",
        border_style="cyan",
    )


def _events_panel(events: tuple[RepoOpenEvent, ...]) -> Panel:
    if not events:
        return Panel(
            Text(
                "No individual repository open events match the current filters.",
                style="dim",
            ),
            title="Repo Open Events (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Timestamp", no_wrap=True)
    table.add_column("ID", no_wrap=True)
    table.add_column("Agent", no_wrap=True)
    table.add_column("Repo")
    table.add_column("Workspace", justify="right", no_wrap=True)
    table.add_column("Reason")

    ordered_events = sorted(
        events,
        key=lambda event: (event.timestamp, event.id),
        reverse=True,
    )
    for event in ordered_events:
        table.add_row(
            event.timestamp,
            event.id,
            event.agent_name,
            event.repo,
            f"#{event.workspace_num}",
            _reason_preview(event.reason),
        )

    return Panel(
        table,
        title=f"Repo Open Events ({len(events)})",
        border_style="cyan",
    )


def _render_repo_open_log_event(
    event: RepoOpenEvent,
    *,
    console: Console | None = None,
    project_name: str,
    repo_filter: str | None = None,
    agent_filter: str | None = None,
    workspace_filter: int | None = None,
) -> None:
    """Print the Rich detail view for one repository-open event."""

    target = console or Console()
    target.print(
        Group(
            _summary_panel(
                (event,),
                project_name=project_name,
                repo_filter=repo_filter,
                agent_filter=agent_filter,
                workspace_filter=workspace_filter,
            ),
            _event_panel(event),
        )
    )


def _event_panel(event: RepoOpenEvent) -> Panel:
    detail = Table.grid(padding=(0, 2))
    detail.add_column(style="bold")
    detail.add_column()
    detail.add_row("ID", event.id)
    detail.add_row("Timestamp", event.timestamp)
    detail.add_row("Project", event.project)
    detail.add_row("Repo", event.repo)
    detail.add_row("Kind", Text(event.repo_kind, style=_KIND_STYLES[event.repo_kind]))
    detail.add_row("Workspace", f"#{event.workspace_num}")
    detail.add_row("Path", event.path)
    detail.add_row("Agent", event.agent_name)
    detail.add_row("Agent source", event.agent_source)
    detail.add_row("Reason", event.reason)
    detail.add_row("CWD", event.cwd)
    detail.add_row("Artifacts dir", event.artifacts_dir or "none")
    return Panel(detail, title=f"Repo Open Event {event.id}", border_style="cyan")


def _select_repo_open_event(
    events: tuple[RepoOpenEvent, ...],
    open_id: str | None,
) -> RepoOpenEvent:
    normalized = _normalized_filter(open_id)
    if normalized is None:
        raise _RepoOpenLogLookupError("repository open id must not be empty")

    exact_matches = tuple(event for event in events if event.id == normalized)
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise _RepoOpenLogLookupError(f"repository open id is not unique: {normalized}")

    prefix_matches = tuple(event for event in events if event.id.startswith(normalized))
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if not prefix_matches:
        raise _RepoOpenLogLookupError(f"unknown repository open id: {normalized}")

    matches = ", ".join(event.id for event in prefix_matches[:_ID_ERROR_MATCH_LIMIT])
    if len(prefix_matches) > _ID_ERROR_MATCH_LIMIT:
        matches += ", ..."
    raise _RepoOpenLogLookupError(
        f"repository open id prefix is ambiguous: {normalized} (matches: {matches})"
    )


def _filter_label(
    repo_filter: str | None,
    agent_filter: str | None,
    workspace_filter: int | None,
) -> str:
    parts: list[str] = []
    repo = _normalized_filter(repo_filter)
    agent = _normalized_filter(agent_filter)
    if repo is not None:
        parts.append(f"repo={repo}")
    if agent is not None:
        parts.append(f"agent={agent}")
    if workspace_filter is not None:
        parts.append(f"workspace={workspace_filter}")
    return ", ".join(parts) if parts else "none"


def _is_drilldown(
    *,
    repo_filter: str | None,
    agent_filter: str | None,
    workspace_filter: int | None,
) -> bool:
    return (
        _normalized_filter(repo_filter) is not None
        or _normalized_filter(agent_filter) is not None
        or workspace_filter is not None
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


__all__ = ["handle_repo_log_command"]
