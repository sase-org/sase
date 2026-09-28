"""Bounded bead and agent catalogs for artifact-reference completion."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from pathlib import Path

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bead_time_presentation import BEAD_CREATED_GLYPH, bead_age_label
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    present_agent_name,
)


_MAX_ENTITY_ROWS = 500


@dataclass(frozen=True, slots=True)
class ArtifactRefBeadCandidate:
    payload: str
    label: str
    detail: str
    updated_at: str
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class ArtifactRefAgentCandidate:
    payload: str
    label: str
    detail: str
    updated_at: float


@dataclass(frozen=True, slots=True)
class ArtifactRefGoalCandidate:
    """One unsettled goal row from the machine-local hot projection."""

    payload: str
    label: str
    detail: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class _ArtifactRefGoalCandidateCatalog:
    """Bounded goal rows plus the number omitted by the provider cap."""

    rows: tuple[ArtifactRefGoalCandidate, ...]
    truncated: int


@dataclass(frozen=True, slots=True)
class _ArtifactRefBeadCandidateCatalog:
    """Bounded bead rows plus the number omitted by the provider cap."""

    rows: tuple[ArtifactRefBeadCandidate, ...]
    truncated: int


@dataclass(frozen=True, slots=True)
class _ArtifactRefAgentCandidateCatalog:
    """Bounded agent rows plus the number omitted by the provider cap."""

    rows: tuple[ArtifactRefAgentCandidate, ...]
    truncated: int


@dataclass(frozen=True, slots=True)
class _BeadCacheEntry:
    token: tuple[int, int] | None
    rows: tuple[Issue, ...]


_BEAD_CACHE: dict[Path, _BeadCacheEntry] = {}


def load_bead_candidate_catalog(
    context: ArtifactRefContext,
) -> _ArtifactRefBeadCandidateCatalog:
    """Load bounded bead rows and retain the exact pre-cap count."""
    try:
        issues = [
            issue
            for store in context.bead_stores
            for issue in _read_cached_bead_store(store.root)
        ]
        issues.sort(key=lambda issue: issue.updated_at, reverse=True)
        return _ArtifactRefBeadCandidateCatalog(
            tuple(_bead_candidate(issue) for issue in issues[:_MAX_ENTITY_ROWS]),
            max(0, len(issues) - _MAX_ENTITY_ROWS),
        )
    except Exception:
        return _ArtifactRefBeadCandidateCatalog((), 0)


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


def _bead_candidate(issue: Issue) -> ArtifactRefBeadCandidate:
    kind = ""
    if issue.tier is BeadTier.EPIC:
        kind = "epic"
    elif issue.issue_type is IssueType.PHASE:
        kind = "phase"
    elif issue.issue_type is IssueType.TASK:
        kind = "task"
    detail = issue.status.value if not kind else f"{issue.status.value} · {kind}"
    # The menu's own age column renders ``updated_at`` for bead *and* agent rows,
    # so the bead's creation age rides here, glyph-labeled and unambiguous.
    if age := bead_age_label(issue.created_at):
        detail = f"{detail} · {BEAD_CREATED_GLYPH} {age}"
    return ArtifactRefBeadCandidate(
        payload=issue.id,
        label=issue.title,
        detail=detail,
        updated_at=issue.updated_at,
        created_at=issue.created_at,
    )


def load_agent_candidate_catalog(
    context: ArtifactRefContext,
) -> _ArtifactRefAgentCandidateCatalog:
    """Load bounded agent rows and retain the exact pre-cap count."""
    try:
        identity = _agent_identity(context)
        rows: list[ArtifactRefAgentCandidate] = []
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
                        ArtifactRefAgentCandidate(
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
        return _ArtifactRefAgentCandidateCatalog(
            tuple(rows[:_MAX_ENTITY_ROWS]),
            max(0, len(rows) - _MAX_ENTITY_ROWS),
        )
    except Exception:
        return _ArtifactRefAgentCandidateCatalog((), 0)


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


def load_goal_candidate_catalog(
    project: str | None,
    context: ArtifactRefContext,
) -> _ArtifactRefGoalCandidateCatalog:
    """Load bounded unsettled-goal rows from the hot projection.

    The projection is machine-local JSON, so this stays fast enough for
    the off-thread completion catalog and never touches the ledger.
    Anything unreadable yields no rows rather than failing completion.
    """
    try:
        key = _goal_project_key(project, context)
        if key is None:
            return _ArtifactRefGoalCandidateCatalog((), 0)
        from sase.goals.store import goal_hot_projection_path

        raw = json.loads(goal_hot_projection_path(key).read_text(encoding="utf-8"))
    except Exception:
        return _ArtifactRefGoalCandidateCatalog((), 0)
    try:
        goals = raw.get("goals") or {}
        rows = [
            ArtifactRefGoalCandidate(
                payload=str(goal_id),
                label=str(row.get("title") or goal_id),
                detail=str(row.get("status") or ""),
                updated_at=str(row.get("updated_at") or ""),
            )
            for goal_id, entry in goals.items()
            for row in [entry.get("row") or {}]
            if row.get("status") in {"draft", "active", "review"}
        ]
    except Exception:
        return _ArtifactRefGoalCandidateCatalog((), 0)
    return _ArtifactRefGoalCandidateCatalog(
        tuple(rows[:_MAX_ENTITY_ROWS]),
        max(0, len(rows) - _MAX_ENTITY_ROWS),
    )


def _goal_project_key(project: str | None, context: ArtifactRefContext) -> str | None:
    """Map the completion project (or selection) to a project key."""
    for ref in (project, context.selected_project):
        if not ref:
            continue
        folded = ref.casefold()
        for candidate in context.projects:
            names = {candidate.name.casefold(), candidate.key.casefold()}
            names.update(alias.casefold() for alias in candidate.aliases)
            if folded in names:
                return candidate.key
        if _SAFE_PROJECT_KEY_RE.fullmatch(ref):
            return ref
    return None


_SAFE_PROJECT_KEY_RE = re.compile(r"[A-Za-z0-9._-]+")


__all__ = [
    "ArtifactRefAgentCandidate",
    "ArtifactRefBeadCandidate",
    "ArtifactRefGoalCandidate",
    "_BEAD_CACHE",
    "_read_cached_bead_store",
    "load_agent_candidate_catalog",
    "load_bead_candidate_catalog",
    "load_goal_candidate_catalog",
]
