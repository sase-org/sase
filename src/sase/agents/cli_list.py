"""``sase agent list`` — list running (and optionally completed) agents."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.integrations.agent_list_entries import AgentListEntry, agent_list_entries
from sase.project_display_names import (
    project_display_name_for,
    humanize_vcs_refs_in_text,
)

_STATUS_COLORS: dict[str, str] = {
    "STARTING": "cyan",
    "RUNNING": "green",
    "QUEUED": "#5F87FF",
    "WAITING": "yellow",
    "DONE": "bright_black",
    "FAILED": "red",
}


def _get_provider_colors() -> dict[str, str]:
    """Return provider colours from plugin metadata and family defaults."""
    from sase.llm_provider.registry import provider_cli_status_color_map

    return provider_cli_status_color_map()


_PROMPT_PRETTY_MAX_CHARS = 80
_PROMPT_JSON_MAX_CHARS = 200


def handle_agents_list(args: argparse.Namespace) -> None:
    """Render the running-agents list view (pretty or JSON)."""
    include_all = bool(getattr(args, "all", False))
    project_filter: str | None = getattr(args, "project", None)
    as_json = bool(getattr(args, "json", False))

    agents = agent_list_entries(include_recent=include_all, project=project_filter)

    if as_json:
        _print_json(agents)
        return

    _print_pretty(agents, include_all=include_all)


def _print_json(agents: list[AgentListEntry]) -> None:
    """Write a stable-shape JSON array to stdout."""
    payload = [_agent_to_json(a) for a in agents]
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _agent_to_json(agent: AgentListEntry) -> dict[str, object]:
    prompt = agent.prompt
    if prompt is not None and len(prompt) > _PROMPT_JSON_MAX_CHARS:
        prompt = prompt[:_PROMPT_JSON_MAX_CHARS]

    started_at_iso = agent.started_at.isoformat() if agent.started_at else None

    return {
        "name": agent.name,
        "project": agent.project,
        "pid": agent.pid,
        "model": agent.model,
        "provider": agent.provider,
        "workspace_num": agent.workspace_num,
        "status": agent.status,
        "status_bucket": agent.status_bucket,
        "duration_seconds": agent.duration_seconds,
        "started_at": started_at_iso,
        "approve": agent.approve,
        "prompt_snippet": prompt,
        "artifacts_dir": agent.artifacts_dir,
        "waiting_for": list(agent.wait.wait_for),
        "wait_for_beads": list(agent.wait.wait_for_beads),
        "wait_runners": agent.wait.wait_runners,
        "wait_runners_explicit": agent.wait.wait_runners_explicit,
        "wait_priority": agent.wait.wait_priority,
        "slot_requested_at": agent.wait.slot_requested_at,
        "runner_slots_in_use": agent.wait.runner_slots_in_use,
        "runner_slot_queue_position": agent.wait.runner_slot_queue_position,
        "runner_slot_queue_size": agent.wait.runner_slot_queue_size,
        "parent_agent_name": agent.parent_agent_name,
        "agent_family": agent.agent_family,
        "agent_family_role": agent.agent_family_role,
        "tribe": agent.tribe,
        "agent_clan": agent.agent_clan,
        "agent_clan_generation": agent.agent_clan_generation,
        "clan_tribe": agent.clan_tribe,
        "runner_slot_holders": list(agent.wait.runner_slot_holders),
        "is_monitor": agent.is_monitor,
        "monitor_id": agent.monitor_id,
        "monitor_state": agent.monitor_state,
        "monitor_label": agent.monitor_label,
        "monitor_command": agent.monitor_command,
        "monitor_exit_code": agent.monitor_exit_code,
    }


def _print_pretty(agents: list[AgentListEntry], *, include_all: bool) -> None:
    console = Console()

    title_label = "Agents" if include_all else "Running Agents"
    title = f"{title_label} ({len(agents)})"

    if not agents:
        console.print(
            Panel(
                Text.from_markup(
                    "[dim]No running agents.[/dim]\n"
                    "Start one with [bold]sase run <xprompt>[/bold] or"
                    " [bold]sase ace[/bold]."
                ),
                title=title,
                border_style="cyan",
            )
        )
        return

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("NAME", style="bold")
    table.add_column("PROJECT")
    table.add_column("WS", justify="right")
    table.add_column("MODEL")
    table.add_column("PROVIDER")
    table.add_column("DURATION", justify="right")
    table.add_column("STATUS")
    table.add_column("PROMPT")

    for agent in agents:
        table.add_row(
            agent.name or "-",
            project_display_name_for(agent.project),
            "-" if agent.workspace_num is None else str(agent.workspace_num),
            agent.model or "-",
            _provider_badge(agent.provider),
            agent.duration,
            _status_badge(agent.status),
            _truncate_prompt(
                humanize_vcs_refs_in_text(agent.prompt) if agent.prompt else None,
                _PROMPT_PRETTY_MAX_CHARS,
            ),
        )

    console.print(Panel(table, title=title, border_style="cyan"))


def _status_badge(status: str) -> Text:
    color = _STATUS_COLORS.get(status, "")
    return Text(status, style=color) if color else Text(status)


def _provider_badge(provider: str | None) -> Text:
    if not provider:
        return Text("-")
    color = _get_provider_colors().get(provider.lower(), "")
    return Text(provider, style=color) if color else Text(provider)


def _truncate_prompt(prompt: str | None, limit: int) -> str:
    if not prompt:
        return "-"
    single_line = prompt.replace("\n", " ").strip()
    if len(single_line) <= limit:
        return single_line
    return single_line[: max(limit - 1, 1)] + "…"
