"""``sase agent show`` — detail panel for a single agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.agent.names import find_named_agent
from sase.core.agent_artifact_paths import parse_agent_artifact_path
from sase.llm_provider.model_label import append_model_field
from sase.project_display_names import (
    project_display_name_for,
    humanize_vcs_refs_in_text,
)


def handle_agents_show(args: argparse.Namespace) -> None:
    """Render a full detail panel for the named agent."""
    name: str = args.name
    agent = find_named_agent(name)
    if agent is None:
        print(f"No agent found with name '{name}'", file=sys.stderr)
        sys.exit(2)

    artifacts_dir = Path(agent.artifacts_dir)
    meta = _read_json(artifacts_dir / "agent_meta.json")
    done = _read_json(artifacts_dir / "done.json") if agent.is_done else None

    body = Text()
    body.append("Name: ", style="bold")
    body.append(f"{name}\n")
    body.append("Status: ", style="bold")
    if agent.is_done:
        outcome = agent.outcome or "completed"
        body.append(f"DONE ({outcome})\n")
    else:
        body.append("RUNNING\n")
    body.append("Artifacts dir: ", style="bold")
    body.append(f"{artifacts_dir}\n")

    info = parse_agent_artifact_path(artifacts_dir)
    project = (
        info.project_name
        if info is not None
        else artifacts_dir.parent.parent.parent.name
    )
    body.append("Project: ", style="bold")
    body.append(f"{project_display_name_for(project)}\n")

    # Uniform ``Model: PROVIDER(model) @ <effort>`` shape shared with the ACE
    # TUI so the effective model/provider/reasoning-effort reads identically.
    append_model_field(
        body,
        _optional_str(meta.get("model")),
        _optional_str(meta.get("llm_provider")),
        _optional_str(meta.get("reasoning_effort")),
        _optional_str(meta.get("model_alias")),
    )
    if meta.get("pid"):
        body.append("PID: ", style="bold")
        body.append(f"{meta['pid']}\n")

    if done:
        if done.get("finished_at"):
            body.append("Finished at: ", style="bold")
            body.append(f"{done['finished_at']}\n")
        if done.get("outcome"):
            body.append("Outcome: ", style="bold")
            body.append(f"{done['outcome']}\n")

    raw_prompt_path = artifacts_dir / "raw_xprompt.md"
    if raw_prompt_path.exists():
        try:
            prompt_text = raw_prompt_path.read_text(encoding="utf-8").strip()
        except OSError:
            prompt_text = "<failed to read prompt>"
        body.append("\nPrompt:\n", style="bold")
        body.append(humanize_vcs_refs_in_text(prompt_text) + "\n")

    if not agent.is_done:
        body.append("\nLive tail: ", style="bold")
        body.append(f"tail -f {artifacts_dir}/live_reply.md\n")

    Console().print(Panel(body, title=f"Agent: {name}", border_style="cyan"))


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


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
