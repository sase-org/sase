"""Git first-add evidence for collided artifact-link event digests.

History lookup is exceptional work for actual collided groups, not a Git walk
for every event on every normal read. Python gathers provenance; sase-core
selects the winner.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sase.sdd._git import run_sdd_git


@dataclass(frozen=True, slots=True)
class ArtifactLinkCollisionEvidence:
    """Durability provenance for one collision candidate."""

    history_complete: bool = False
    first_commit_id: str | None = None
    first_commit_at: str | None = None
    ancestor_commit_ids: tuple[str, ...] = ()
    admission_sequence: int | None = None

    def to_wire(self) -> dict[str, object]:
        wire: dict[str, object] = {"history_complete": self.history_complete}
        if self.first_commit_id is not None:
            wire["first_commit_id"] = self.first_commit_id
        if self.first_commit_at is not None:
            wire["first_commit_at"] = self.first_commit_at
        if self.ancestor_commit_ids:
            wire["ancestor_commit_ids"] = list(self.ancestor_commit_ids)
        if self.admission_sequence is not None:
            wire["admission_sequence"] = self.admission_sequence
        return wire


def attach_collision_history(
    candidates: Sequence[Any],
    *,
    collided_digests: Iterable[str],
) -> tuple[Any, ...]:
    """Fill Git first-add evidence on collided candidates that have a root."""

    needed = frozenset(collided_digests)
    if not needed:
        return tuple(candidates)
    grouped: dict[str, list[Any]] = {}
    query_roots: list[Path] = []
    seen_query_roots: set[Path] = set()
    for candidate in candidates:
        digest = str(getattr(candidate, "digest", "") or "")
        root = getattr(candidate, "root", None)
        if digest not in needed or not root:
            continue
        grouped.setdefault(str(root), []).append(candidate)
        resolved = Path(str(root)).expanduser().resolve(strict=False)
        if resolved in seen_query_roots:
            continue
        seen_query_roots.add(resolved)
        if _is_git_repo(resolved) and not _is_shallow_repository(resolved):
            query_roots.append(resolved)
    if not grouped:
        return tuple(candidates)
    first_adds: dict[tuple[str, str], ArtifactLinkCollisionEvidence] = {}
    for root, members in grouped.items():
        first_adds.update(_root_first_adds(Path(root), members))
    ancestors_by_key = _cross_root_ancestors(query_roots, first_adds)
    updated: list[Any] = []
    for candidate in candidates:
        digest = str(getattr(candidate, "digest", "") or "")
        root = getattr(candidate, "root", None)
        if not root:
            updated.append(candidate)
            continue
        key = (str(root), digest)
        extra = first_adds.get(key)
        if extra is None:
            updated.append(candidate)
            continue
        current = getattr(candidate, "evidence", ArtifactLinkCollisionEvidence())
        if not isinstance(current, ArtifactLinkCollisionEvidence):
            current = ArtifactLinkCollisionEvidence()
        ancestors = ancestors_by_key.get(key, extra.ancestor_commit_ids)
        updated.append(
            replace(
                candidate,
                evidence=ArtifactLinkCollisionEvidence(
                    history_complete=extra.history_complete,
                    first_commit_id=extra.first_commit_id,
                    first_commit_at=extra.first_commit_at,
                    ancestor_commit_ids=ancestors,
                    admission_sequence=current.admission_sequence,
                ),
            )
        )
    return tuple(updated)


def collided_digests_for(
    candidates: Iterable[Any],
) -> frozenset[str]:
    """Return digests that share a project/operation id with a different digest."""

    by_operation: dict[tuple[str, str], set[str]] = {}
    for candidate in candidates:
        event = getattr(candidate, "event", None)
        if not isinstance(event, Mapping):
            continue
        project_key = str(event.get("project_key") or "")
        operation_id = str(event.get("operation_id") or "")
        digest = str(getattr(candidate, "digest", "") or "")
        if not project_key or not operation_id or not digest:
            continue
        by_operation.setdefault((project_key, operation_id), set()).add(digest)
    collided: set[str] = set()
    for digests in by_operation.values():
        if len(digests) > 1:
            collided.update(digests)
    return frozenset(collided)


def _root_first_adds(
    root: Path,
    members: Sequence[Any],
) -> dict[tuple[str, str], ArtifactLinkCollisionEvidence]:
    if not _is_git_repo(root):
        return {}
    if _is_shallow_repository(root):
        incomplete: dict[tuple[str, str], ArtifactLinkCollisionEvidence] = {}
        for candidate in members:
            digest = str(getattr(candidate, "digest", "") or "")
            relative = getattr(candidate, "relative_path", None)
            if not digest or not relative:
                continue
            incomplete[(str(root), digest)] = ArtifactLinkCollisionEvidence(
                history_complete=False,
            )
        return incomplete
    result: dict[tuple[str, str], ArtifactLinkCollisionEvidence] = {}
    for candidate in members:
        digest = str(getattr(candidate, "digest", "") or "")
        relative = getattr(candidate, "relative_path", None)
        if not digest or not relative:
            continue
        first_add = _first_add_commit(root, str(relative))
        if first_add is None:
            continue
        commit_id, commit_at = first_add
        result[(str(root), digest)] = ArtifactLinkCollisionEvidence(
            history_complete=True,
            first_commit_id=commit_id,
            first_commit_at=commit_at,
        )
    return result


def _cross_root_ancestors(
    query_roots: Sequence[Path],
    first_adds: Mapping[tuple[str, str], ArtifactLinkCollisionEvidence],
) -> dict[tuple[str, str], tuple[str, ...]]:
    """Prove ancestry among known first-add commits wherever objects exist."""

    complete: dict[tuple[str, str], str] = {}
    for key, evidence in first_adds.items():
        commit_id = evidence.first_commit_id
        if evidence.history_complete and commit_id:
            complete[key] = commit_id
    unique_commits = tuple(dict.fromkeys(complete.values()))
    if len(unique_commits) < 2 or not query_roots:
        return dict.fromkeys(complete, ())
    ancestors_of: dict[str, set[str]] = {commit: set() for commit in unique_commits}
    for descendant in unique_commits:
        for ancestor in unique_commits:
            if ancestor == descendant:
                continue
            if _is_ancestor_in_any(query_roots, ancestor, descendant):
                ancestors_of[descendant].add(ancestor)
    return {
        key: tuple(sorted(ancestors_of.get(commit_id, ())))
        for key, commit_id in complete.items()
    }


def _first_add_commit(root: Path, relative_path: str) -> tuple[str, str] | None:
    result = run_sdd_git(
        [
            "log",
            "--diff-filter=A",
            "--format=%H%x09%cI",
            "--",
            relative_path,
        ],
        cwd=root,
        op="artifact-link-collision-first-add",
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    commit_id, separator, commit_at = lines[-1].partition("\t")
    if not separator or len(commit_id.strip()) < 7 or not commit_at.strip():
        return None
    return commit_id.strip(), commit_at.strip()


def _is_ancestor_in_any(roots: Sequence[Path], ancestor: str, descendant: str) -> bool:
    return any(_is_ancestor(root, ancestor, descendant) for root in roots)


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    if ancestor == descendant:
        return False
    result = run_sdd_git(
        ["merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        op="artifact-link-collision-ancestor",
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _is_git_repo(root: Path) -> bool:
    result = run_sdd_git(
        ["rev-parse", "--is-inside-work-tree"],
        cwd=root,
        op="artifact-link-collision-git-probe",
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _is_shallow_repository(root: Path) -> bool:
    result = run_sdd_git(
        ["rev-parse", "--is-shallow-repository"],
        cwd=root,
        op="artifact-link-collision-shallow-probe",
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


__all__ = [
    "ArtifactLinkCollisionEvidence",
    "attach_collision_history",
    "collided_digests_for",
]
