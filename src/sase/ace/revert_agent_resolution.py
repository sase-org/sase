"""Agent-row resolution helpers for commit reverts."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.revert_agent_models import RevertRepo
from sase.plan_chain import agent_family_base

if TYPE_CHECKING:
    from sase.ace.tui.models import Agent
    from sase.ace.tui.models.agent import LinkedRepoMetadata


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


def resolve_revert_repos(agent: Agent) -> tuple[RevertRepo, ...]:
    """Resolve primary plus linked repository workspaces for an agent revert.

    Linked-repo sourcing is deliberately status-agnostic: the action layer has
    already limited reverts to done/failed agents, and reusing linked-DELTAS
    eligibility here would exclude exactly those rows.
    """
    primary_dir = resolve_revert_workspace_dir(agent)
    repos: list[RevertRepo] = []
    seen_dirs: set[str] = set()

    if primary_dir:
        repos.append(
            RevertRepo(label="primary", workspace_dir=primary_dir, is_primary=True)
        )
        seen_dirs.add(_dedup_workspace_key(primary_dir))

    for linked in _suffix_workspace_linked_repos_for_revert(agent):
        workspace_dir = _existing_workspace_dir(linked.workspace_dir)
        if workspace_dir is None:
            continue
        key = _dedup_workspace_key(workspace_dir)
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        repos.append(
            RevertRepo(
                label=linked.name,
                workspace_dir=workspace_dir,
                is_primary=False,
            )
        )

    return tuple(repos)


def resolve_revert_repos_for_agents(
    agents: Sequence[Agent],
) -> tuple[RevertRepo, ...]:
    """Return the ordered union of revert repos across *agents*."""
    repos: list[RevertRepo] = []
    seen_dirs: set[str] = set()
    for agent in agents:
        for repo in resolve_revert_repos(agent):
            key = _dedup_workspace_key(repo.workspace_dir)
            if key in seen_dirs:
                continue
            seen_dirs.add(key)
            repos.append(repo)
    return tuple(repos)


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


def _existing_workspace_dir(workspace_dir: str) -> str | None:
    expanded = os.path.expanduser(workspace_dir)
    if not os.path.isdir(expanded):
        return None
    return os.path.normpath(expanded)


def _dedup_workspace_key(workspace_dir: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(workspace_dir)))


def _suffix_workspace_linked_repos_for_revert(
    agent: Agent,
) -> tuple[LinkedRepoMetadata, ...]:
    repos: list[LinkedRepoMetadata] = []
    seen_names: set[str] = set()
    for repo in agent.linked_repos:
        if repo.name in seen_names:
            continue
        seen_names.add(repo.name)
        if repo.workspace_strategy != "suffix":
            continue
        if not repo.workspace_dir:
            continue
        repos.append(repo)
    return tuple(repos)


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
    "_suffix_workspace_linked_repos_for_revert",
    "resolve_revert_agent_name",
    "resolve_revert_family_base",
    "resolve_revert_repos",
    "resolve_revert_repos_for_agents",
    "resolve_revert_workspace_dir",
]
