"""Persistence helpers for plan approval notification actions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent


def persist_plan_approved(agent: Agent, action: str = "approve") -> None:
    """Write plan_approved flag to agent_meta.json so it survives TUI restarts.

    Args:
        agent: The agent whose plan was approved.
        action: The plan action taken: "approve", "commit", "epic", or "legend".
    """
    artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
    if not artifacts_dir:
        return

    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta: dict[str, object] = {}
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    meta["plan_approved"] = True
    meta["plan_action"] = action
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except OSError:
        pass
