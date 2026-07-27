"""Filesystem path resolution for associated plans."""

from __future__ import annotations

import os
from pathlib import Path

from sase.core.paths import shorten_path
from sase.sdd.plan_refs import (
    PlanReferenceResolution,
    resolve_plan_reference as resolve_shared_plan_reference,
    resolve_plan_reference_from_roots,
)

from ._agent_associated_plan_types import PlanAssociationCacheKey
from .agent import Agent


def association_key(
    agent: Agent,
    source: str,
    value: str,
) -> PlanAssociationCacheKey:
    return (
        source,
        value,
        agent_project_name(agent),
        _normalized_workspace_dir(agent.workspace_dir),
        agent.effective_workspace_num or 1,
    )


def resolve_plan_reference(reference: str, agent: Agent) -> Path:
    resolution = _resolve_plan_reference_resolution(reference, agent)
    if resolution.best_path is not None:
        return resolution.best_path
    return Path(reference).expanduser().resolve(strict=False)


def _resolve_plan_reference_resolution(
    reference: str,
    agent: Agent,
) -> PlanReferenceResolution:
    """Return the shared resolution outcome, preserving legacy workspace files."""

    workspace_dir = _agent_workspace_dir(agent)
    workspace_num = agent.effective_workspace_num or 1
    resolution_dir = workspace_dir or Path.cwd()
    raw_path = Path(reference).expanduser()
    if raw_path.is_absolute():
        resolution = resolve_plan_reference_from_roots(reference, roots=())
    else:
        resolution = resolve_shared_plan_reference(
            reference,
            workspace_dir=resolution_dir,
            workspace_num=workspace_num,
        )
    if resolution.resolved_path is not None:
        return resolution

    try:
        fallback = (
            raw_path if raw_path.is_absolute() else resolution_dir / raw_path
        ).resolve(strict=False)
        fallback_is_file = fallback.is_file()
    except (OSError, ValueError):
        return resolution
    if not fallback_is_file:
        return resolution
    return PlanReferenceResolution(
        schema_version=resolution.schema_version,
        status="exact",
        resolved_path=fallback,
        candidates=(*resolution.candidates, fallback),
    )


def display_plan_path(
    path: Path,
    agent: Agent,
    *,
    committed: bool,
) -> str:
    if committed:
        workspace_dir = _agent_workspace_dir(agent)
        if workspace_dir is not None:
            try:
                return path.relative_to(workspace_dir).as_posix()
            except ValueError:
                pass
    return shorten_path(str(path))


def _agent_workspace_dir(agent: Agent) -> Path | None:
    if agent.workspace_dir:
        return Path(agent.workspace_dir).expanduser().resolve(strict=False)
    if not agent.project_file:
        return None
    try:
        from sase.workspace_provider.utils import parse_workspace_dir

        workspace_dir = parse_workspace_dir(agent.project_file)
    except Exception:
        return None
    if not workspace_dir:
        return None
    return Path(workspace_dir).expanduser().resolve(strict=False)


def agent_project_name(agent: Agent) -> str | None:
    if not agent.project_file:
        return None
    return Path(agent.project_file).parent.name or None


def _normalized_workspace_dir(workspace_dir: str | None) -> str | None:
    if not workspace_dir:
        return None
    return os.path.normpath(os.path.expanduser(workspace_dir))
