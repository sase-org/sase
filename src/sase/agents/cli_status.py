"""``sase agents status`` — list running (and optionally completed) agents."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.agent.running import (
    RunningAgentInfo,
    list_all_agents,
    list_running_agents,
)

_STATUS_COLORS: dict[str, str] = {
    "RUNNING": "green",
    "WAITING": "yellow",
    "DONE": "bright_black",
    "FAILED": "red",
}

_PROVIDER_COLORS: dict[str, str] = {
    "claude": "#D97757",
    "anthropic": "#D97757",
    "gemini": "#4285F4",
    "codex": "#10A37F",
    "openai": "#10A37F",
    "jetski": "magenta",
}

_PROMPT_PRETTY_MAX_CHARS = 80
_PROMPT_JSON_MAX_CHARS = 200


def handle_agents_status(args: argparse.Namespace) -> None:
    """Render the running-agents status view (pretty or JSON)."""
    include_all = bool(getattr(args, "all", False))
    project_filter: str | None = getattr(args, "project", None)
    as_json = bool(getattr(args, "json", False))

    agents = list_all_agents() if include_all else list_running_agents()

    if project_filter:
        agents = [a for a in agents if a.project == project_filter]

    if as_json:
        _print_json(agents)
        return

    _print_pretty(agents, include_all=include_all)


def _print_json(agents: list[RunningAgentInfo]) -> None:
    """Write a stable-shape JSON array to stdout."""
    payload = [_agent_to_json(a) for a in agents]
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _agent_to_json(agent: RunningAgentInfo) -> dict[str, object]:
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
        "duration_seconds": agent.duration_seconds,
        "started_at": started_at_iso,
        "approve": agent.approve,
        "prompt_snippet": prompt,
        "artifacts_dir": agent.artifacts_dir,
    }


def _print_pretty(agents: list[RunningAgentInfo], *, include_all: bool) -> None:
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
            agent.project,
            "-" if agent.workspace_num is None else str(agent.workspace_num),
            agent.model or "-",
            _provider_badge(agent.provider),
            agent.duration,
            _status_badge(agent.status),
            _truncate_prompt(agent.prompt, _PROMPT_PRETTY_MAX_CHARS),
        )

    console.print(Panel(table, title=title, border_style="cyan"))


def _status_badge(status: str) -> Text:
    color = _STATUS_COLORS.get(status, "")
    return Text(status, style=color) if color else Text(status)


def _provider_badge(provider: str | None) -> Text:
    if not provider:
        return Text("-")
    color = _PROVIDER_COLORS.get(provider.lower(), "")
    return Text(provider, style=color) if color else Text(provider)


def _truncate_prompt(prompt: str | None, limit: int) -> str:
    if not prompt:
        return "-"
    single_line = prompt.replace("\n", " ").strip()
    if len(single_line) <= limit:
        return single_line
    return single_line[: max(limit - 1, 1)] + "…"
