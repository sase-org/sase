"""Filesystem path resolution for associated plans."""

from __future__ import annotations

import os
from pathlib import Path

from sase.core.paths import shorten_path

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
    raw_path = Path(reference).expanduser()
    if raw_path.is_absolute():
        return raw_path.resolve(strict=False)

    workspace_dir = _agent_workspace_dir(agent)
    workspace_num = agent.effective_workspace_num or 1
    candidates: list[Path] = []
    if workspace_dir is not None:
        candidates.append(workspace_dir / raw_path)
        primary = _primary_workspace_dir(workspace_dir, workspace_num)
        if primary is not None:
            candidates.append(primary / raw_path)
        candidates.extend(_sdd_plan_candidates(workspace_dir, workspace_num, raw_path))
    if not candidates:
        candidates.append(raw_path)

    normalized = _dedupe_paths(candidates)
    for candidate in normalized:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return normalized[0]


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


def _primary_workspace_dir(workspace_dir: Path, workspace_num: int) -> Path | None:
    try:
        from sase.sdd._paths import get_primary_workspace_dir

        primary = get_primary_workspace_dir(str(workspace_dir), workspace_num)
    except Exception:
        return None
    return Path(primary).expanduser().resolve(strict=False) if primary else None


def _sdd_plan_candidates(
    workspace_dir: Path,
    workspace_num: int,
    reference: Path,
) -> list[Path]:
    try:
        from sase.sdd.store import resolve_sdd_store

        plan_root = resolve_sdd_store(workspace_dir, workspace_num).kind_root("plans")
    except Exception:
        return []

    parts = reference.parts
    relative = reference
    for prefix in (
        (".sase", "sdd", "plans"),
        ("sdd", "plans"),
        ("plans",),
    ):
        if parts[: len(prefix)] == prefix:
            relative = Path(*parts[len(prefix) :])
            break
    return [plan_root / relative]


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        normalized = path.expanduser().resolve(strict=False)
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def agent_project_name(agent: Agent) -> str | None:
    if not agent.project_file:
        return None
    return Path(agent.project_file).parent.name or None


def _normalized_workspace_dir(workspace_dir: str | None) -> str | None:
    if not workspace_dir:
        return None
    return os.path.normpath(os.path.expanduser(workspace_dir))
