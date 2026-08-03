"""Rich and JSON rendering for ``sase skill log`` summaries."""

from __future__ import annotations

import argparse
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
from sase.main.init_memory.config import project_memory_name
from sase.skills.use_log import (
    SkillUseEvent,
    filter_skill_use_events,
    read_skill_use_events,
    summarize_skill_uses_by_agent,
    summarize_skill_uses_by_runtime,
    summarize_skill_uses_by_skill,
)

_REASON_PREVIEW_WIDTH = 72
_ID_ERROR_MATCH_LIMIT = 5


class _SkillsLogLookupError(ValueError):
    """Raised when a requested skill-use event cannot be selected."""


def handle_skills_log_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Render or serialize the project-scoped skill-use summary."""
    root = Path.cwd()
    project_name = project_memory_name(root)
    events = read_skill_use_events(project=project_name)
    agent_filter = getattr(args, "agent", None)
    runtime_filter = getattr(args, "runtime", None)
    skill_filter = getattr(args, "skill", None)
    use_id = getattr(args, "id", None)
    filtered_events = filter_skill_use_events(
        events,
        agent_name=agent_filter,
        runtime=runtime_filter,
        skill_name=skill_filter,
    )

    if _normalized_filter(use_id) is not None:
        try:
            event = _select_skill_use_event(filtered_events, use_id)
        except _SkillsLogLookupError as exc:
            print(f"sase skill log: {exc}", file=sys.stderr)
            sys.exit(1)

        if getattr(args, "json", False):
            json.dump(asdict(event), sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return

        _render_skills_log_event(
            event,
            console=console,
            project_name=project_name,
            agent_filter=agent_filter,
            runtime_filter=runtime_filter,
            skill_filter=skill_filter,
        )
        return

    if getattr(args, "json", False):
        payload = _build_skills_log_summary_payload(
            filtered_events,
            project_name=project_name,
            agent_filter=agent_filter,
            runtime_filter=runtime_filter,
            skill_filter=skill_filter,
        )
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return

    _render_skills_log_summary(
        filtered_events,
        console=console,
        project_name=project_name,
        agent_filter=agent_filter,
        runtime_filter=runtime_filter,
        skill_filter=skill_filter,
    )


def _render_skills_log_summary(
    events: tuple[SkillUseEvent, ...],
    *,
    console: Console | None = None,
    project_name: str,
    agent_filter: str | None = None,
    runtime_filter: str | None = None,
    skill_filter: str | None = None,
) -> None:
    """Print the Rich summary dashboard for skill-use events."""
    event_tuple = tuple(events)
    target = console or Console()
    target.print(
        _build_skills_log_summary_dashboard(
            event_tuple,
            project_name=project_name,
            agent_filter=agent_filter,
            runtime_filter=runtime_filter,
            skill_filter=skill_filter,
        )
    )


def _build_skills_log_summary_payload(
    events: tuple[SkillUseEvent, ...],
    *,
    project_name: str,
    agent_filter: str | None = None,
    runtime_filter: str | None = None,
    skill_filter: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic JSON payload for the summary view."""
    event_tuple = tuple(events)
    summaries = summarize_skill_uses_by_skill(event_tuple)
    return {
        "filters": {
            "agent": _normalized_filter(agent_filter),
            "runtime": _normalized_filter(runtime_filter),
            "skill": _normalized_filter(skill_filter),
        },
        "project": project_name,
        "summary": [asdict(summary) for summary in summaries],
        "total_agents": len({event.agent_name for event in event_tuple}),
        "total_runtimes": len({_runtime_label(event.runtime) for event in event_tuple}),
        "total_skill_uses": len(event_tuple),
        "total_skills": len({event.skill_name for event in event_tuple}),
    }


def _build_skills_log_summary_dashboard(
    events: tuple[SkillUseEvent, ...],
    *,
    project_name: str,
    agent_filter: str | None = None,
    runtime_filter: str | None = None,
    skill_filter: str | None = None,
) -> Group:
    """Build the static Rich dashboard for the skill-use summary."""
    panels: list[Panel] = [
        _summary_panel(
            events,
            project_name=project_name,
            agent_filter=agent_filter,
            runtime_filter=runtime_filter,
            skill_filter=skill_filter,
        ),
        _skills_panel(
            events,
            agent_filter=agent_filter,
            runtime_filter=runtime_filter,
            skill_filter=skill_filter,
        ),
    ]
    if _normalized_filter(agent_filter) is not None:
        panels.append(_agents_panel(events))
    if _normalized_filter(runtime_filter) is not None:
        panels.append(_runtimes_panel(events))
    if _is_drilldown(
        agent_filter=agent_filter,
        runtime_filter=runtime_filter,
        skill_filter=skill_filter,
    ):
        panels.append(_events_panel(events))
    return Group(*panels)


def _summary_panel(
    events: tuple[SkillUseEvent, ...],
    *,
    project_name: str,
    agent_filter: str | None = None,
    runtime_filter: str | None = None,
    skill_filter: str | None = None,
) -> Panel:
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Project", project_name)
    summary.add_row(
        "Filters",
        _filter_label(
            agent_filter=agent_filter,
            runtime_filter=runtime_filter,
            skill_filter=skill_filter,
        ),
    )
    summary.add_row("Skill uses", str(len(events)))
    summary.add_row("Skills", str(len({event.skill_name for event in events})))
    summary.add_row("Agents", str(len({event.agent_name for event in events})))
    summary.add_row(
        "Runtimes",
        str(len({_runtime_label(event.runtime) for event in events})),
    )
    return Panel(summary, title="SASE Skill Use Log", border_style="cyan")


def _skills_panel(
    events: tuple[SkillUseEvent, ...],
    *,
    agent_filter: str | None = None,
    runtime_filter: str | None = None,
    skill_filter: str | None = None,
) -> Panel:
    summaries = summarize_skill_uses_by_skill(events)
    if not summaries:
        message = (
            "No skill-use events match the current filters."
            if _filter_label(
                agent_filter=agent_filter,
                runtime_filter=runtime_filter,
                skill_filter=skill_filter,
            )
            != "none"
            else "No skill-use events found."
        )
        return Panel(
            Text(message, style="dim"),
            title="Skills (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Skill")
    table.add_column("Uses", justify="right", no_wrap=True)
    table.add_column("Agents", justify="right", no_wrap=True)
    table.add_column("Last used", no_wrap=True)
    table.add_column("Last agent", no_wrap=True)
    table.add_column("Last reason")

    for summary in summaries:
        table.add_row(
            summary.skill_name,
            str(summary.use_count),
            str(summary.distinct_agent_count),
            format_local(summary.last_used_at),
            summary.last_agent,
            _reason_preview(summary.last_reason),
        )

    return Panel(table, title=f"Skills ({len(summaries)})", border_style="cyan")


def _agents_panel(events: tuple[SkillUseEvent, ...]) -> Panel:
    summaries = summarize_skill_uses_by_agent(events)
    if not summaries:
        return Panel(
            Text("No agents match the current filters.", style="dim"),
            title="Agents (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Agent")
    table.add_column("Uses", justify="right", no_wrap=True)
    table.add_column("Skills", justify="right", no_wrap=True)
    table.add_column("Last used", no_wrap=True)
    table.add_column("Last skill")
    table.add_column("Last reason")

    for summary in summaries:
        table.add_row(
            summary.agent_name,
            str(summary.use_count),
            str(summary.distinct_skill_count),
            format_local(summary.last_used_at),
            summary.last_skill,
            _reason_preview(summary.last_reason),
        )

    return Panel(table, title=f"Agents ({len(summaries)})", border_style="cyan")


def _runtimes_panel(events: tuple[SkillUseEvent, ...]) -> Panel:
    summaries = summarize_skill_uses_by_runtime(events)
    if not summaries:
        return Panel(
            Text("No runtimes match the current filters.", style="dim"),
            title="Runtimes (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Runtime")
    table.add_column("Uses", justify="right", no_wrap=True)
    table.add_column("Skills", justify="right", no_wrap=True)
    table.add_column("Agents", justify="right", no_wrap=True)
    table.add_column("Last used", no_wrap=True)
    table.add_column("Last reason")

    for summary in summaries:
        table.add_row(
            summary.runtime,
            str(summary.use_count),
            str(summary.distinct_skill_count),
            str(summary.distinct_agent_count),
            format_local(summary.last_used_at),
            _reason_preview(summary.last_reason),
        )

    return Panel(table, title=f"Runtimes ({len(summaries)})", border_style="cyan")


def _events_panel(events: tuple[SkillUseEvent, ...]) -> Panel:
    if not events:
        return Panel(
            Text(
                "No individual skill-use events match the current filters.",
                style="dim",
            ),
            title="Skill Use Events (0)",
            border_style="cyan",
        )

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("ID", no_wrap=True)
    table.add_column("Timestamp", no_wrap=True)
    table.add_column("Agent", no_wrap=True)
    table.add_column("Runtime", no_wrap=True)
    table.add_column("Skill")
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
            _runtime_label(event.runtime),
            event.skill_name,
            _reason_preview(event.reason),
        )

    return Panel(
        table,
        title=f"Skill Use Events ({len(events)})",
        border_style="cyan",
    )


def _render_skills_log_event(
    event: SkillUseEvent,
    *,
    console: Console | None = None,
    project_name: str,
    agent_filter: str | None = None,
    runtime_filter: str | None = None,
    skill_filter: str | None = None,
) -> None:
    """Print the Rich detail view for one skill-use event."""
    target = console or Console()
    target.print(
        _build_skills_log_event_dashboard(
            event,
            project_name=project_name,
            agent_filter=agent_filter,
            runtime_filter=runtime_filter,
            skill_filter=skill_filter,
        )
    )


def _build_skills_log_event_dashboard(
    event: SkillUseEvent,
    *,
    project_name: str,
    agent_filter: str | None = None,
    runtime_filter: str | None = None,
    skill_filter: str | None = None,
) -> Group:
    return Group(
        _summary_panel(
            (event,),
            project_name=project_name,
            agent_filter=agent_filter,
            runtime_filter=runtime_filter,
            skill_filter=skill_filter,
        ),
        _event_panel(event),
    )


def _event_panel(event: SkillUseEvent) -> Panel:
    detail = Table.grid(padding=(0, 2))
    detail.add_column(style="bold")
    detail.add_column()
    detail.add_row("ID", event.id)
    detail.add_row("Timestamp", format_local(event.timestamp))
    detail.add_row("Project", event.project)
    detail.add_row("Skill", event.skill_name)
    detail.add_row("Agent", event.agent_name)
    detail.add_row("Agent source", event.agent_source)
    detail.add_row("Runtime", _runtime_label(event.runtime))
    detail.add_row("Reason", event.reason)
    detail.add_row("CWD", event.cwd)
    detail.add_row("Artifacts dir", event.artifacts_dir or "none")
    return Panel(detail, title=f"Skill Use Event {event.id}", border_style="cyan")


def _select_skill_use_event(
    events: tuple[SkillUseEvent, ...],
    use_id: str | None,
) -> SkillUseEvent:
    normalized = _normalized_filter(use_id)
    if normalized is None:
        raise _SkillsLogLookupError("skill-use event id must not be empty")

    exact_matches = tuple(event for event in events if event.id == normalized)
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise _SkillsLogLookupError(f"skill-use event id is not unique: {normalized}")

    prefix_matches = tuple(event for event in events if event.id.startswith(normalized))
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if not prefix_matches:
        raise _SkillsLogLookupError(f"unknown skill-use event id: {normalized}")

    matches = ", ".join(event.id for event in prefix_matches[:_ID_ERROR_MATCH_LIMIT])
    if len(prefix_matches) > _ID_ERROR_MATCH_LIMIT:
        matches += ", ..."
    raise _SkillsLogLookupError(
        f"skill-use event id prefix is ambiguous: {normalized} (matches: {matches})"
    )


def _filter_label(
    *,
    agent_filter: str | None = None,
    runtime_filter: str | None = None,
    skill_filter: str | None = None,
) -> str:
    parts: list[str] = []
    agent = _normalized_filter(agent_filter)
    runtime = _normalized_filter(runtime_filter)
    skill = _normalized_filter(skill_filter)
    if agent is not None:
        parts.append(f"agent={agent}")
    if runtime is not None:
        parts.append(f"runtime={runtime}")
    if skill is not None:
        parts.append(f"skill={skill}")
    return ", ".join(parts) if parts else "none"


def _is_drilldown(
    *,
    agent_filter: str | None = None,
    runtime_filter: str | None = None,
    skill_filter: str | None = None,
) -> bool:
    return (
        _normalized_filter(agent_filter) is not None
        or _normalized_filter(runtime_filter) is not None
        or _normalized_filter(skill_filter) is not None
    )


def _normalized_filter(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _runtime_label(runtime: str | None) -> str:
    normalized = _normalized_filter(runtime)
    return normalized or "unknown"


def _reason_preview(reason: str) -> str:
    one_line = " ".join(reason.split())
    if len(one_line) <= _REASON_PREVIEW_WIDTH:
        return one_line
    return one_line[: _REASON_PREVIEW_WIDTH - 3].rstrip() + "..."
