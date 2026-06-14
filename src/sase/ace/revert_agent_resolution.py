"""Agent-row resolution helpers for commit reverts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from sase.plan_chain import agent_family_base

if TYPE_CHECKING:
    from sase.ace.tui.models import Agent


def resolve_revert_agent_name(agent: Agent) -> str | None:
    """Resolve the canonical agent name for revert provenance matching.

    Prefers the ``name`` recorded in ``agent_meta.json`` (authoritative for the
    ``AGENT=`` tag), falling back to :attr:`Agent.agent_name`.
    """
    artifacts_dir = agent.get_artifacts_dir()
    if artifacts_dir:
        meta_name = _agent_name_from_meta(artifacts_dir)
        if meta_name:
            return meta_name
    name = getattr(agent, "agent_name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def resolve_revert_workspace_dir(agent: Agent) -> str | None:
    """Resolve the git workspace directory the agent ran in."""
    from sase.ace.tui.widgets.prompt_panel._file_path_hints import (
        resolve_agent_workspace_dir,
    )

    return resolve_agent_workspace_dir(
        agent.effective_workspace_num,
        agent.project_file,
        agent.workspace_dir,
    )


def resolve_revert_family_base(agent: Agent, agent_name: str | None) -> str | None:
    """Resolve the agent-family base for family-scoped reverts, if any.

    Plan-chain rows carry an explicit ``agent_family``; otherwise the base is
    inferred from a family-suffixed name. ``None`` means exact selected-agent
    scope.
    """
    family = getattr(agent, "agent_family", None)
    if isinstance(family, str) and family.strip():
        return family.strip()
    if agent_name:
        return agent_family_base(agent_name)
    return None


def _agent_name_from_meta(artifacts_dir: str) -> str | None:
    try:
        meta = json.loads(
            (Path(artifacts_dir) / "agent_meta.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(meta, dict):
        name = meta.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


__all__ = [
    "resolve_revert_agent_name",
    "resolve_revert_family_base",
    "resolve_revert_workspace_dir",
]
