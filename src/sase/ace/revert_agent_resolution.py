"""Agent-row resolution helpers for commit reverts."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.patch.project_spec_path import project_spec_basename
from sase.ace.revert_agent_models import BulkRevertIntent, RevertIntent, RevertRepo
from sase.linked_repos import opened_external_repo_records
from sase.plan_chain import agent_family_base

if TYPE_CHECKING:
    from collections.abc import Sequence as _Sequence

    from sase.ace.revert_agent_models import (
        BulkRevertPreview,
        RevertPreview,
        RevertTarget,
    )
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
    """Resolve primary, linked, and external repos for an agent revert.

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

    for linked in _workspace_linked_repos_for_revert(agent):
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

    for external in _external_repos_for_revert(agent):
        workspace_dir = _existing_workspace_dir(external.workspace_dir)
        if workspace_dir is None:
            continue
        key = _dedup_workspace_key(workspace_dir)
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        repos.append(
            RevertRepo(
                label=external.label,
                workspace_dir=workspace_dir,
                is_primary=False,
                repo_kind="external",
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


def build_revert_intent(
    agent: Agent,
    agent_name: str,
    family_base: str | None,
) -> RevertIntent:
    """Capture immutable single-agent revert intent from an agent row.

    The intent carries stable provenance (project, target scope, agent name,
    family base, artifacts dir, and the suffix-linked repo names the run touched)
    so the backend can claim a fresh workspace instead of reusing the directory
    the agent originally ran in.
    """
    return RevertIntent(
        project_file=agent.project_file,
        project_basename=project_spec_basename(agent.project_file),
        cl_name=agent.cl_name,
        agent_name=agent_name,
        is_project_scoped=agent.is_project_agent,
        family_base=family_base,
        artifacts_dir=agent.get_artifacts_dir(),
        linked_repo_names=_suffix_linked_repo_names(agent),
        external_artifact_dirs=_external_artifact_dirs_for_revert(
            agent,
            source_agent_name=agent_name,
        ),
    )


def build_bulk_revert_intent(
    targets: _Sequence[RevertTarget],
    target_agents: _Sequence[Agent],
    representative: Agent,
) -> BulkRevertIntent:
    """Capture immutable bulk revert intent for marked agents.

    Bulk reverts run against a single project and scope (taken from
    *representative*); ``linked_repo_names`` is the ordered union of
    suffix-linked repos touched across *target_agents*.
    """
    return BulkRevertIntent(
        project_file=representative.project_file,
        project_basename=project_spec_basename(representative.project_file),
        cl_name=representative.cl_name,
        is_project_scoped=representative.is_project_agent,
        targets=tuple(targets),
        linked_repo_names=_union_suffix_linked_repo_names(target_agents),
        external_artifact_dirs=_union_external_artifact_dirs_for_revert(
            targets,
            target_agents,
        ),
    )


def build_revert_execute_intent(
    agent: Agent,
    preview: RevertPreview,
    artifacts_dir: str | None,
) -> RevertIntent:
    """Rebuild single-agent revert intent for the execute phase.

    Execute reverts the exact previewed SHAs, so the discovery-only family base
    is irrelevant; the linked repos to re-prepare are exactly those that carried
    a plan in the confirmed preview.
    """
    return RevertIntent(
        project_file=agent.project_file,
        project_basename=project_spec_basename(agent.project_file),
        cl_name=agent.cl_name,
        agent_name=preview.agent_name,
        is_project_scoped=agent.is_project_agent,
        family_base=None,
        artifacts_dir=artifacts_dir,
        linked_repo_names=_preview_linked_repo_names(preview),
        external_repos=_preview_external_repos(preview),
    )


def build_bulk_revert_execute_intent(
    representative: Agent,
    preview: BulkRevertPreview,
) -> BulkRevertIntent:
    """Rebuild bulk revert intent for the execute phase from the confirmed preview."""
    return BulkRevertIntent(
        project_file=representative.project_file,
        project_basename=project_spec_basename(representative.project_file),
        cl_name=representative.cl_name,
        is_project_scoped=representative.is_project_agent,
        targets=preview.targets,
        linked_repo_names=_preview_linked_repo_names(preview),
        external_repos=_preview_external_repos(preview),
    )


def _preview_linked_repo_names(
    preview: RevertPreview | BulkRevertPreview,
) -> tuple[str, ...]:
    """Ordered, deduplicated non-primary repo labels carried by a preview."""
    names: list[str] = []
    seen: set[str] = set()
    for plan in preview.repos:
        if plan.is_primary or plan.repo_kind == "external" or plan.repo_label in seen:
            continue
        seen.add(plan.repo_label)
        names.append(plan.repo_label)
    return tuple(names)


def _preview_external_repos(
    preview: RevertPreview | BulkRevertPreview,
) -> tuple[RevertRepo, ...]:
    """Return the external clone paths carried by a confirmed preview."""
    return tuple(
        RevertRepo(
            label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            repo_kind="external",
            source_agent_names=plan.source_agent_names,
        )
        for plan in preview.repos
        if plan.repo_kind == "external"
    )


def _suffix_linked_repo_names(agent: Agent) -> tuple[str, ...]:
    """Ordered linked repo names recorded for *agent*."""
    return tuple(repo.name for repo in _workspace_linked_repos_for_revert(agent))


def _union_suffix_linked_repo_names(
    agents: _Sequence[Agent],
) -> tuple[str, ...]:
    """Ordered union of linked repo names across *agents*."""
    names: list[str] = []
    seen: set[str] = set()
    for agent in agents:
        for name in _suffix_linked_repo_names(agent):
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
    return tuple(names)


def _external_repos_for_revert(
    agent: Agent,
    *,
    source_agent_name: str | None = None,
) -> tuple[RevertRepo, ...]:
    """Return external repositories recorded in an agent-family's markers."""
    return external_repos_from_artifact_dirs(
        _external_artifact_dirs_for_revert(
            agent,
            source_agent_name=source_agent_name,
        )
    )


def _external_artifact_dirs_for_revert(
    agent: Agent,
    *,
    source_agent_name: str | None = None,
) -> tuple[tuple[str, str], ...]:
    """Collect marker roots without performing filesystem I/O."""
    artifacts: list[tuple[str, str]] = []
    pending = [agent]
    seen_agents: set[tuple[object, ...]] = set()
    seen_dirs: set[str] = set()
    while pending:
        member = pending.pop(0)
        if member.identity in seen_agents:
            continue
        seen_agents.add(member.identity)
        pending.extend(member.followup_agents)
        artifacts_dir = member.artifacts_dir
        if not artifacts_dir:
            continue
        normalized = os.path.normcase(
            os.path.abspath(os.path.expanduser(artifacts_dir))
        )
        if normalized in seen_dirs:
            continue
        seen_dirs.add(normalized)
        artifacts.append((source_agent_name or "", artifacts_dir))
    return tuple(artifacts)


def external_repos_from_artifact_dirs(
    artifact_dirs: Sequence[tuple[str, str]],
) -> tuple[RevertRepo, ...]:
    """Load and merge external-repo markers from tracked-worker inputs."""
    repos: dict[tuple[str, str], RevertRepo] = {}
    order: list[tuple[str, str]] = []
    for source_agent_name, artifacts_dir in artifact_dirs:
        records = opened_external_repo_records(
            Path(artifacts_dir).expanduser().resolve(strict=False)
        )
        for name, record in records.items():
            workspace_dir = record.get("workspace_dir", "")
            key = (name, _dedup_workspace_key(workspace_dir))
            if not workspace_dir:
                continue
            source_names = (source_agent_name,) if source_agent_name else ()
            existing = repos.get(key)
            if existing is not None:
                source_names = tuple(
                    dict.fromkeys((*existing.source_agent_names, *source_names))
                )
            else:
                order.append(key)
            repos[key] = RevertRepo(
                label=name,
                workspace_dir=workspace_dir,
                repo_kind="external",
                source_agent_names=source_names,
            )
    return tuple(repos[key] for key in order)


def _union_external_artifact_dirs_for_revert(
    targets: _Sequence[RevertTarget],
    agents: _Sequence[Agent],
) -> tuple[tuple[str, str], ...]:
    """Return marker roots across bulk targets with source owners."""
    artifact_dirs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for target, agent in zip(targets, agents, strict=False):
        for source_name, artifacts_dir in _external_artifact_dirs_for_revert(
            agent,
            source_agent_name=target.agent_name,
        ):
            key = (source_name, _dedup_workspace_key(artifacts_dir))
            if key in seen:
                continue
            seen.add(key)
            artifact_dirs.append((source_name, artifacts_dir))
    return tuple(artifact_dirs)


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


def _workspace_linked_repos_for_revert(
    agent: Agent,
) -> tuple[LinkedRepoMetadata, ...]:
    repos: list[LinkedRepoMetadata] = []
    seen_names: set[str] = set()
    for repo in agent.linked_repos:
        if repo.name in seen_names:
            continue
        seen_names.add(repo.name)
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
    "_workspace_linked_repos_for_revert",
    "build_bulk_revert_execute_intent",
    "build_bulk_revert_intent",
    "build_revert_execute_intent",
    "build_revert_intent",
    "external_repos_from_artifact_dirs",
    "resolve_revert_agent_name",
    "resolve_revert_family_base",
    "resolve_revert_repos",
    "resolve_revert_repos_for_agents",
    "resolve_revert_workspace_dir",
]
