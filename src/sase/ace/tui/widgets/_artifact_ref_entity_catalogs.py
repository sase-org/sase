"""Bounded bead and agent catalogs for artifact-reference completion."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.model import BeadTier, Issue, IssueType
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    present_agent_name,
)


_MAX_ENTITY_ROWS = 500


@dataclass(frozen=True, slots=True)
class _ArtifactRefBeadCandidate:
    payload: str
    label: str
    detail: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class _ArtifactRefAgentCandidate:
    payload: str
    label: str
    detail: str
    updated_at: float


@dataclass(frozen=True, slots=True)
class _BeadCacheEntry:
    token: tuple[int, int] | None
    rows: tuple[Issue, ...]


_BEAD_CACHE: dict[Path, _BeadCacheEntry] = {}


def _load_bead_candidates(
    context: ArtifactRefContext,
) -> tuple[_ArtifactRefBeadCandidate, ...]:
    """Load the newest bead rows from the context's scoped stores."""
    try:
        issues = [
            issue
            for store in context.bead_stores
            for issue in _read_cached_bead_store(store.root)
        ]
        issues.sort(key=lambda issue: issue.updated_at, reverse=True)
        return tuple(_bead_candidate(issue) for issue in issues[:_MAX_ENTITY_ROWS])
    except Exception:
        return ()


def _read_cached_bead_store(root: Path) -> tuple[Issue, ...]:
    resolved = root.expanduser().resolve(strict=False)
    index_path = resolved / "issues.jsonl"
    try:
        stat = index_path.stat()
        token: tuple[int, int] | None = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        token = None
    cached = _BEAD_CACHE.get(resolved)
    if cached is not None and cached.token == token:
        return cached.rows
    if token is None:
        rows: tuple[Issue, ...] = ()
    else:
        try:
            from sase.core.bead_read_facade import list_issues

            rows = tuple(list_issues(resolved))
        except Exception:
            rows = ()
    _BEAD_CACHE[resolved] = _BeadCacheEntry(token, rows)
    return rows


def _bead_candidate(issue: Issue) -> _ArtifactRefBeadCandidate:
    kind = ""
    if issue.tier is BeadTier.EPIC:
        kind = "epic"
    elif issue.issue_type is IssueType.PHASE:
        kind = "phase"
    detail = issue.status.value if not kind else f"{issue.status.value} · {kind}"
    return _ArtifactRefBeadCandidate(
        payload=issue.id,
        label=issue.title,
        detail=detail,
        updated_at=issue.updated_at,
    )


def _load_agent_candidates(
    context: ArtifactRefContext,
) -> tuple[_ArtifactRefAgentCandidate, ...]:
    """Scan the newest published agent pages from the scoped sidecar."""
    try:
        identity = _agent_identity(context)
        rows: list[_ArtifactRefAgentCandidate] = []
        for root in context.agent_roots:
            with os.scandir(root.root / "agents") as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if not (Path(entry.path) / "README.md").is_file():
                        continue
                    name = entry.name
                    label = present_agent_name(name, identity)
                    rows.append(
                        _ArtifactRefAgentCandidate(
                            payload=name,
                            label=label,
                            detail=_agent_detail(
                                name,
                                label,
                                root.project,
                                context,
                            ),
                            updated_at=entry.stat(follow_symlinks=False).st_mtime,
                        )
                    )
        rows.sort(
            key=lambda row: (-row.updated_at, row.payload.casefold(), row.payload)
        )
        return tuple(rows[:_MAX_ENTITY_ROWS])
    except Exception:
        return ()


def _agent_identity(context: ArtifactRefContext) -> AgentIdentitySnapshot:
    owner = context.agent_owner
    if owner is None:
        return AgentIdentitySnapshot.unconfigured()
    return AgentIdentitySnapshot(
        AgentOwnerIdentity(owner.username, owner.machine_name),
    )


def _agent_detail(
    name: str,
    label: str,
    project: str,
    context: ArtifactRefContext,
) -> str:
    owner = context.agent_owner
    if owner is None or label != name:
        return project
    parts = name.split(".")
    offset = 1 if len(parts) >= 4 and len(parts[0]) == 6 and parts[0].isdigit() else 0
    if len(parts) < offset + 3:
        return project
    prefix = ".".join(parts[offset : offset + 2])
    local_prefix = f"{owner.username}.{owner.machine_name}"
    return project if prefix == local_prefix else prefix


__all__ = [
    "_ArtifactRefAgentCandidate",
    "_ArtifactRefBeadCandidate",
    "_BEAD_CACHE",
    "_load_agent_candidates",
    "_load_bead_candidates",
    "_read_cached_bead_store",
]
