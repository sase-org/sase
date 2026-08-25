"""Tribe-reference source resolution for named-agent fork sources."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import sase_projects_dir
from sase.core.wait_dependency_resolution import (
    TribeCandidate,
    WaitDependencyIndex,
    read_json_dict,
)
from sase.scripts._agent_chat_from_name_common import completed_response_path
from sase.scripts._agent_chat_from_name_models import (
    ForkClanMemberSource,
    ForkSource,
)


def resolve_tribe_fork_source(reference: str, tribe: str) -> ForkSource:
    """Resolve a tribe ref to the wait side's canonical next complete entity.

    The implied wait normally makes an unresolved result unreachable. Rebuilding
    the all-project index here preserves the wait check's entity aggregation and
    earliest-launch ordering when the fork workflow starts after the barrier.
    """
    from sase.core.agent_tribe import (
        is_reserved_tribe_name,
        reserved_tribe_target_reason,
    )

    if is_reserved_tribe_name(tribe):
        raise RuntimeError(
            f"Invalid '#fork' tribe reference {reference!r}: "
            f"{reserved_tribe_target_reason(tribe)}"
        )

    current_artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not current_artifacts_dir:
        raise RuntimeError(
            f"Cannot resolve tribe fork target {reference!r}: "
            "SASE_ARTIFACTS_DIR is not set"
        )

    current = Path(current_artifacts_dir).expanduser().resolve(strict=False)
    candidate = _build_all_projects_wait_index().tribe_candidate(
        tribe,
        newer_than=current.name,
        exclude_artifact_dir=current,
    )
    if candidate is None:
        raise RuntimeError(
            f"No completed @{tribe} entity launched after {current.name}"
        )
    return _fork_source_from_tribe_candidate(candidate)


def _build_all_projects_wait_index() -> WaitDependencyIndex:
    """Build the same cross-project artifact index used by wait-check chops."""
    projects_dir = sase_projects_dir()
    index = WaitDependencyIndex.empty()
    if not projects_dir.exists():
        return index

    artifact_rows: list[tuple[Path, dict[str, Any], str]] = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for artifact_dir in iter_agent_artifact_dirs(
            project_dir.name,
            "ace-run",
            projects_root=projects_dir,
        ):
            meta = read_json_dict(artifact_dir / "agent_meta.json")
            if meta is not None:
                artifact_rows.append((artifact_dir, meta, project_dir.name))
    index.add_many(artifact_rows)
    return index


def _fork_source_from_tribe_candidate(candidate: TribeCandidate) -> ForkSource:
    """Project a selected wait candidate into the fork workflow source wire."""
    if candidate.kind == "agent":
        member = candidate.members[0]
        path = completed_response_path(
            member.name,
            Path(member.artifact_dir),
            archived_completion=member.archived_completion,
        )
        return ForkSource(kind="agent", name=member.name, path=path)

    members = tuple(
        ForkClanMemberSource(
            name=member.name,
            path=completed_response_path(
                member.name,
                Path(member.artifact_dir),
                archived_completion=member.archived_completion,
                clan_member=True,
            ),
            artifact_dir=member.artifact_dir,
        )
        for member in sorted(candidate.members, key=lambda item: item.timestamp)
    )
    newest_member = max(members, key=lambda member: Path(member.artifact_dir).name)
    return ForkSource(
        kind="clan",
        name=candidate.name,
        path=newest_member.path,
        generation=candidate.generation,
        tribe=candidate.tribe,
        members=members,
    )
