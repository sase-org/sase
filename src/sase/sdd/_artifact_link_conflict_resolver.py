"""Resolve mergeable artifact-link index conflicts in SDD sidecars."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from sase.agents_sync.io import atomic_write_json
from sase.bead.conflict_resolver_git import (
    git_add,
    read_git_show,
    unmerged_stages,
    upstream_and_local_stages,
)
from sase.core.artifact_link_conflict_facade import merge_artifact_link_indexes
from sase.sdd._artifact_link_files import is_canonical_artifact_link_index_location
from sase.sdd._artifact_link_store_support import ARTIFACT_LINK_ROW_SCHEMA_VERSION


@dataclass(frozen=True)
class _ArtifactLinkConflictResolution:
    ok: bool
    message: str
    resolved_files: tuple[str, ...] = ()


def is_artifact_link_conflict_path(repo_root: Path, path: str) -> bool:
    """Return whether *path* is a canonical-location link index."""

    return is_canonical_artifact_link_index_location(repo_root / path, repo_root)


def resolve_artifact_link_conflicts(
    repo_root: Path,
    paths: tuple[str, ...],
) -> _ArtifactLinkConflictResolution:
    """Resolve preclaimed artifact-link conflicts, failing closed on ambiguity."""

    if not paths:
        return _ArtifactLinkConflictResolution(True, "no artifact-link conflicts")

    merges: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(paths):
        if not is_artifact_link_conflict_path(repo_root, path):
            return _ArtifactLinkConflictResolution(
                False,
                "unsupported artifact-link conflicts: " + path,
            )
        prepared = _prepare_merge(repo_root, path)
        if not prepared.ok:
            return _ArtifactLinkConflictResolution(False, prepared.message)
        assert prepared.merged is not None
        merges.append((path, prepared.merged))

    for path, merged in merges:
        atomic_write_json(repo_root / path, merged)
    git_add(repo_root, [path for path, _merged in merges])
    resolved = tuple(path for path, _merged in merges)
    return _ArtifactLinkConflictResolution(
        True,
        "resolved artifact-link conflicts: " + ", ".join(resolved),
        resolved,
    )


@dataclass(frozen=True)
class _PreparedMerge:
    ok: bool
    message: str
    merged: dict[str, Any] | None = None


def _prepare_merge(repo_root: Path, path: str) -> _PreparedMerge:
    try:
        stages = unmerged_stages(repo_root, path)
        if stages == frozenset({1, 2, 3}):
            base = _read_stage_index(repo_root, path, 1)
            upstream_stage, local_stage = upstream_and_local_stages(repo_root)
            ours = _read_stage_index(repo_root, path, local_stage)
            theirs = _read_stage_index(repo_root, path, upstream_stage)
        elif stages == frozenset({2, 3}):
            upstream_stage, local_stage = upstream_and_local_stages(repo_root)
            ours = _read_stage_index(repo_root, path, local_stage)
            theirs = _read_stage_index(repo_root, path, upstream_stage)
            artifact_ref = _artifact_ref_for_empty_base(ours, theirs)
            if artifact_ref is None:
                return _PreparedMerge(
                    False,
                    f"malformed artifact-link conflict {path}: "
                    "both-added stages do not name artifact_ref",
                )
            base = {
                "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                "artifact_ref": artifact_ref,
                "rows": [],
            }
        elif stages in (frozenset({1, 2}), frozenset({1, 3})):
            return _PreparedMerge(
                False,
                f"unsupported artifact-link conflict {path}: modify/delete stages "
                + ",".join(str(stage) for stage in sorted(stages)),
            )
        else:
            return _PreparedMerge(
                False,
                f"unsupported artifact-link conflict {path}: unexpected stages "
                + ",".join(str(stage) for stage in sorted(stages)),
            )
    except ValueError as exc:
        return _PreparedMerge(
            False,
            f"malformed artifact-link conflict stage for {path}: {exc}",
        )

    try:
        merged = merge_artifact_link_indexes(base, ours, theirs)
    except (TypeError, ValueError, RuntimeError, AttributeError) as exc:
        return _PreparedMerge(
            False,
            f"artifact-link conflict resolution failed for {path}: {exc}",
        )
    return _PreparedMerge(True, "resolved", merged)


def _read_stage_index(repo_root: Path, path: str, stage: int) -> dict[str, Any]:
    text = read_git_show(repo_root, stage, path)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"stage {stage} is not valid JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"stage {stage} is not a JSON object")
    return payload


def _artifact_ref_for_empty_base(
    ours: dict[str, Any],
    theirs: dict[str, Any],
) -> str | None:
    for candidate in (ours.get("artifact_ref"), theirs.get("artifact_ref")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return None


__all__ = [
    "is_artifact_link_conflict_path",
    "resolve_artifact_link_conflicts",
]
