"""Shared semantic conflict resolver chain for SDD git rebases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.bead.conflict_resolver import (
    BeadConflictResolution,
    resolve_bead_conflicts_for_paths,
)
from sase.bead.conflict_resolver_git import (
    GitProbeFailure,
    conflicted_files,
    git_repo_root,
)
from sase.bead.conflict_resolver_paths import (
    is_bead_path,
    resolve_beads_dir,
)
from sase.bead.project import BEADS_DIRNAME_ROOT
from sase.bead.relocation import BeadIdRelocation
from sase.sdd._artifact_link_conflict_resolver import (
    is_artifact_link_conflict_path,
    resolve_artifact_link_conflicts,
)


@dataclass(frozen=True)
class _SemanticConflictResolution:
    ok: bool
    message: str
    resolved_files: tuple[str, ...] = ()
    bead_relocations: tuple[BeadIdRelocation, ...] = ()


def resolve_semantic_conflicts(
    cwd: str | Path = ".",
    *,
    beads_dir: str | Path | None = None,
) -> _SemanticConflictResolution:
    """Resolve every currently unmerged path claimed by a semantic resolver."""

    try:
        return _resolve_semantic_conflicts(Path(cwd), beads_dir)
    except GitProbeFailure as error:
        return _SemanticConflictResolution(False, str(error))


def _resolve_semantic_conflicts(
    cwd: Path,
    beads_dir: str | Path | None,
) -> _SemanticConflictResolution:
    repo_root = git_repo_root(cwd)
    if repo_root is None:
        return _SemanticConflictResolution(False, "not inside a git repository")

    conflicted = conflicted_files(repo_root)
    if not conflicted:
        return _SemanticConflictResolution(True, "no semantic conflicts")

    resolved_beads_dir = resolve_beads_dir(repo_root, beads_dir)
    bead_prefix: str | None = None
    if resolved_beads_dir is not None:
        bead_prefix = resolved_beads_dir.relative_to(repo_root).as_posix()
        if bead_prefix == BEADS_DIRNAME_ROOT:
            bead_prefix = ""

    bead_conflicts: list[str] = []
    link_conflicts: list[str] = []
    unclaimed: list[str] = []
    for path in conflicted:
        if bead_prefix is not None and is_bead_path(path, bead_prefix):
            bead_conflicts.append(path)
        elif is_artifact_link_conflict_path(repo_root, path):
            link_conflicts.append(path)
        else:
            unclaimed.append(path)

    if unclaimed:
        prefix = (
            "non-bead conflicts remain: "
            if not link_conflicts
            else "non-semantic conflicts remain: "
        )
        return _SemanticConflictResolution(False, prefix + ", ".join(unclaimed))

    resolved: list[str] = []
    bead_relocations: tuple[BeadIdRelocation, ...] = ()
    if bead_conflicts:
        bead_result = resolve_bead_conflicts_for_paths(
            repo_root,
            tuple(bead_conflicts),
            beads_dir=resolved_beads_dir,
        )
        if not bead_result.ok:
            return _from_bead_resolution(bead_result)
        resolved.extend(bead_result.resolved_files)
        bead_relocations = bead_result.bead_relocations

    if link_conflicts:
        link_result = resolve_artifact_link_conflicts(
            repo_root,
            tuple(link_conflicts),
        )
        if not link_result.ok:
            return _SemanticConflictResolution(
                False,
                link_result.message,
                tuple(sorted(dict.fromkeys(resolved))),
                bead_relocations,
            )
        resolved.extend(link_result.resolved_files)

    message = "resolved semantic conflicts: " + ", ".join(
        sorted(dict.fromkeys(resolved))
    )
    if bead_relocations:
        message += "; relocated duplicate beads: " + ", ".join(
            f"{relocation.old_id} -> {relocation.new_id}"
            for relocation in bead_relocations
        )
    return _SemanticConflictResolution(
        True,
        message,
        tuple(sorted(dict.fromkeys(resolved))),
        bead_relocations,
    )


def _from_bead_resolution(
    resolution: BeadConflictResolution,
) -> _SemanticConflictResolution:
    return _SemanticConflictResolution(
        resolution.ok,
        resolution.message,
        resolution.resolved_files,
        resolution.bead_relocations,
    )


__all__ = [
    "resolve_semantic_conflicts",
]
