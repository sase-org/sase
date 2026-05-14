"""``sase agents show`` — detail panel for a single agent."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.agent.names import NamedAgent, find_named_agent
from sase.agents.daemon_reads import (
    AgentShowData,
    load_agent_show_by_handle,
    load_agent_show_by_name,
    project_id_from_agent_id,
)
from sase.daemon.read_facade import read_or_fallback


def handle_agents_show(args: argparse.Namespace) -> None:
    """Render a full detail panel for the named agent."""
    name: str = args.name
    show_data = _load_show_data(args, name)
    if show_data is None:
        print(f"No agent found with name '{name}'", file=sys.stderr)
        sys.exit(2)
    _render_show_data(show_data, panel_name=name)


@dataclass(frozen=True)
class _DirectShowData:
    agent: NamedAgent
    meta: dict[str, object]
    done: dict[str, object] | None
    prompt_text: str | None


def _load_show_data(args: argparse.Namespace, name: str) -> AgentShowData | None:
    direct = _load_direct_show_data(name)
    daemon_project: str | None = getattr(args, "project", None)
    is_handle = project_id_from_agent_id(name) is not None

    if not is_handle and not daemon_project:
        direct_data = direct()
        return None if direct_data is None else _direct_to_show_data(name, direct_data)

    result = read_or_fallback(
        "agent_detail",
        args=args,
        client=getattr(args, "_daemon_client", None),
        daemon_loader=lambda client: (
            load_agent_show_by_handle(
                client,
                agent_id=name,
                project_id=daemon_project,
            )
            if is_handle
            else load_agent_show_by_name(
                client, name=name, project_id=daemon_project or ""
            )
        ),
        direct_loader=lambda: (
            None if (data := direct()) is None else _direct_to_show_data(name, data)
        ),
        required_capability="agents.read",
    )
    return result.value


def _load_direct_show_data(name: str) -> Callable[[], _DirectShowData | None]:
    def load() -> _DirectShowData | None:
        agent = find_named_agent(name)
        if agent is None:
            return None

        artifacts_dir = Path(agent.artifacts_dir)
        meta = _read_json(artifacts_dir / "agent_meta.json")
        done = _read_json(artifacts_dir / "done.json") if agent.is_done else None
        prompt_text = _read_prompt(artifacts_dir / "raw_xprompt.md")
        return _DirectShowData(
            agent=agent, meta=meta, done=done, prompt_text=prompt_text
        )

    return load


def _direct_to_show_data(name: str, data: _DirectShowData) -> AgentShowData:
    agent = data.agent
    artifacts_dir = Path(agent.artifacts_dir)
    if agent.is_done:
        outcome = agent.outcome or "completed"
        status_line = f"DONE ({outcome})"
    else:
        outcome = None
        status_line = "RUNNING"

    return AgentShowData(
        name=name,
        status_line=status_line,
        artifacts_dir=str(artifacts_dir),
        project=artifacts_dir.parent.parent.parent.name,
        model=_dict_str(data.meta, "model"),
        provider=_dict_str(data.meta, "llm_provider"),
        pid=_dict_int(data.meta, "pid"),
        finished_at=_dict_label(data.done or {}, "finished_at"),
        outcome=_dict_str(data.done or {}, "outcome") or outcome,
        prompt_text=data.prompt_text,
        live_tail=not agent.is_done,
    )


def _render_show_data(show_data: AgentShowData, *, panel_name: str) -> None:
    artifacts_dir = Path(show_data.artifacts_dir)

    body = Text()
    body.append("Name: ", style="bold")
    body.append(f"{show_data.name}\n")
    body.append("Status: ", style="bold")
    body.append(f"{show_data.status_line}\n")
    body.append("Artifacts dir: ", style="bold")
    body.append(f"{artifacts_dir}\n")

    body.append("Project: ", style="bold")
    body.append(f"{show_data.project}\n")

    if show_data.model:
        body.append("Model: ", style="bold")
        body.append(f"{show_data.model}\n")
    if show_data.provider:
        body.append("Provider: ", style="bold")
        body.append(f"{show_data.provider}\n")
    if show_data.pid:
        body.append("PID: ", style="bold")
        body.append(f"{show_data.pid}\n")

    if show_data.finished_at:
        body.append("Finished at: ", style="bold")
        body.append(f"{show_data.finished_at}\n")
    if show_data.outcome:
        body.append("Outcome: ", style="bold")
        body.append(f"{show_data.outcome}\n")

    if show_data.prompt_text:
        body.append("\nPrompt:\n", style="bold")
        body.append(show_data.prompt_text + "\n")

    if show_data.live_tail:
        body.append("\nLive tail: ", style="bold")
        body.append(f"tail -f {artifacts_dir}/live_reply.md\n")

    Console().print(Panel(body, title=f"Agent: {panel_name}", border_style="cyan"))


def _read_prompt(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return "<failed to read prompt>"


def _dict_str(values: dict[str, object], key: str) -> str | None:
    value = values.get(key)
    return value if isinstance(value, str) else None


def _dict_int(values: dict[str, object], key: str) -> int | None:
    value = values.get(key)
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _dict_label(values: dict[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    return str(value)


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return loaded
