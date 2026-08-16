"""Snapshot-based family plan-preview resolution for the editor helper.

The agent-catalog helper is a short-lived subprocess behind a 5 s timeout,
so this module bounds work per call: plan-file reads are deduped by resolved
path, and only the most recent :data:`_FAMILY_PREVIEW_LIMIT` families are
enriched. Failures degrade to an empty preview rather than raising.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from sase.agent.bead_display import BeadIssueLookupSession, lookup_bead_issue
from sase.agent_family_plan_preview import (
    EMPTY_AGENT_FAMILY_PLAN_PREVIEW,
    AgentFamilyPlanPreview,
    agent_family_plan_preview_from_bead,
    agent_family_plan_preview_from_plan,
)
from sase.bead.model import Issue, IssueType
from sase.phase_size_presentation import normalize_phase_size
from sase.sdd.plan_display import load_plan_display

#: Newest families to enrich per catalog call. Older families keep the
#: historical ``family · N members`` detail. Lower this if catalog wall time
#: grows more than ~150 ms on a realistic artifact store.
_FAMILY_PREVIEW_LIMIT: Final = 20
_LEFTOVER_HASH_REF_RE = re.compile(
    r"^#[A-Za-z][\w-]*(?:!!|\?\?)?(?:\([^)]*\)|[_:][^\s]+)?\s*"
)


@dataclass(frozen=True, slots=True)
class _FamilyPlanMember:
    """Plan, bead, and snippet fields for one newest-generation family member."""

    artifact_dir: str
    timestamp: str
    plan_path: str | None
    archived_plan_path: str | None
    sdd_plan_path: str | None
    epic_plan_ref: str | None
    epic_bead_id: str | None
    phase_bead_id: str | None
    raw_prompt_snippet: str | None
    workspace_dir: str | None
    project_name: str | None
    workspace_num: int | None


@dataclass(frozen=True, slots=True)
class FamilyPlanPreviewResult:
    """Resolved preview plus the stripped prompt snippet used as fallback."""

    preview: AgentFamilyPlanPreview
    fallback_title: str


def enrich_catalog_families(
    snapshot: Any,
    families: Sequence[tuple[str, Sequence[tuple[str, str]]]],
) -> dict[str, FamilyPlanPreviewResult]:
    """Resolve previews for the most recent families on one snapshot.

    *families* is ``(name, ((artifact_dir, timestamp), ...) in root-then-
    member order)``. Only :data:`_FAMILY_PREVIEW_LIMIT` families are
    indexed and resolved; older families are omitted. Never raises.
    """
    try:
        ranked = sorted(
            ((name, tuple(members)) for name, members in families if members),
            key=lambda item: max(
                (timestamp for _dir, timestamp in item[1]), default=""
            ),
            reverse=True,
        )[:_FAMILY_PREVIEW_LIMIT]
        contexts = _family_plan_members_from_snapshot(
            snapshot,
            (
                artifact_dir
                for _name, members in ranked
                for artifact_dir, _ts in members
            ),
        )
        return _resolve_family_plan_previews(
            [
                (
                    name,
                    tuple(
                        contexts[artifact_dir]
                        for artifact_dir, _timestamp in members
                        if artifact_dir in contexts
                    ),
                )
                for name, members in ranked
            ]
        )
    except Exception:
        return {}


def _family_plan_members_from_snapshot(
    snapshot: Any,
    artifact_dirs: Iterable[str],
) -> dict[str, _FamilyPlanMember]:
    """Index matching snapshot records by ``artifact_dir``."""
    wanted = {directory for directory in artifact_dirs if directory}
    if not wanted:
        return {}
    members: dict[str, _FamilyPlanMember] = {}
    for record in getattr(snapshot, "records", ()) or ():
        artifact_dir = getattr(record, "artifact_dir", None)
        if not artifact_dir or artifact_dir not in wanted:
            continue
        members[str(artifact_dir)] = _member_from_record(record)
    return members


def _resolve_family_plan_previews(
    families: Sequence[tuple[str, Sequence[_FamilyPlanMember]]],
) -> dict[str, FamilyPlanPreviewResult]:
    ranked = sorted(
        ((name, tuple(members)) for name, members in families if members),
        key=lambda item: max((member.timestamp for member in item[1]), default=""),
        reverse=True,
    )
    selected = ranked[:_FAMILY_PREVIEW_LIMIT]
    results: dict[str, FamilyPlanPreviewResult] = {}
    plan_cache: dict[str, AgentFamilyPlanPreview] = {}
    with BeadIssueLookupSession() as lookup_session:
        for name, members in selected:
            try:
                preview = _resolve_one_family(
                    members,
                    plan_cache=plan_cache,
                    lookup_session=lookup_session,
                )
                results[name] = FamilyPlanPreviewResult(
                    preview=preview,
                    fallback_title=_fallback_title(members),
                )
            except Exception:
                continue
    return results


def _resolve_one_family(
    members: Sequence[_FamilyPlanMember],
    *,
    plan_cache: dict[str, AgentFamilyPlanPreview],
    lookup_session: BeadIssueLookupSession,
) -> AgentFamilyPlanPreview:
    for member in members:
        for raw_path in _plan_path_candidates(member):
            preview = _preview_from_plan_path(
                raw_path,
                member,
                plan_cache=plan_cache,
            )
            if not preview.is_empty:
                return preview
    return _resolve_bead_preview(members, lookup_session=lookup_session)


def _plan_path_candidates(member: _FamilyPlanMember) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in (
        member.plan_path,
        member.archived_plan_path,
        member.sdd_plan_path,
        member.epic_plan_ref,
    ):
        text = (value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return tuple(ordered)


def _preview_from_plan_path(
    raw: str,
    member: _FamilyPlanMember,
    *,
    plan_cache: dict[str, AgentFamilyPlanPreview],
) -> AgentFamilyPlanPreview:
    path = _resolve_plan_file_path(raw, member)
    if path is None:
        return EMPTY_AGENT_FAMILY_PLAN_PREVIEW
    key = str(path)
    cached = plan_cache.get(key)
    if cached is not None:
        return cached
    try:
        preview = agent_family_plan_preview_from_plan(load_plan_display(path))
    except Exception:
        preview = EMPTY_AGENT_FAMILY_PLAN_PREVIEW
    plan_cache[key] = preview
    return preview


def _resolve_plan_file_path(raw: str, member: _FamilyPlanMember) -> Path | None:
    try:
        expanded = Path(raw).expanduser()
    except (OSError, RuntimeError, TypeError, ValueError):
        expanded = Path(str(raw))
    try:
        if expanded.is_file():
            return expanded.resolve(strict=False)
    except OSError:
        pass
    if expanded.is_absolute():
        return _resolved_or_self(expanded)
    if raw.startswith("plan:") or member.workspace_dir:
        resolved = _resolve_plan_reference(raw, member)
        if resolved is not None:
            return resolved
    if member.workspace_dir:
        return _resolved_or_self(Path(member.workspace_dir).expanduser() / expanded)
    return _resolved_or_self(expanded)


def _resolve_plan_reference(raw: str, member: _FamilyPlanMember) -> Path | None:
    try:
        from sase.sdd.plan_refs import (
            resolve_plan_reference,
            resolve_plan_reference_from_roots,
        )
    except Exception:
        return None
    workspace = member.workspace_dir
    if workspace:
        try:
            resolution = resolve_plan_reference(
                raw,
                workspace_dir=workspace,
                workspace_num=member.workspace_num or 1,
            )
        except Exception:
            resolution = None
        if resolution is not None and resolution.best_path is not None:
            return resolution.best_path
    if not raw.startswith("plan:"):
        return None
    try:
        from sase.core.paths import sase_subdir

        resolution = resolve_plan_reference_from_roots(
            raw,
            roots=(sase_subdir("plans"),),
        )
    except Exception:
        return None
    return resolution.best_path


def _resolved_or_self(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return path


def _resolve_bead_preview(
    members: Sequence[_FamilyPlanMember],
    *,
    lookup_session: BeadIssueLookupSession,
) -> AgentFamilyPlanPreview:
    seen: set[str] = set()
    for member in members:
        for bead_id in (member.phase_bead_id, member.epic_bead_id):
            text = (bead_id or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            try:
                issue = lookup_bead_issue(
                    text,
                    project_name=member.project_name,
                    workspace_dir=member.workspace_dir,
                    lookup_session=lookup_session,
                )
            except Exception:
                continue
            if issue is None:
                continue
            preview = _preview_from_issue(
                issue,
                member,
                lookup_session=lookup_session,
            )
            if preview is not None and not preview.is_empty:
                return preview
    return EMPTY_AGENT_FAMILY_PLAN_PREVIEW


def _preview_from_issue(
    issue: Issue,
    member: _FamilyPlanMember,
    *,
    lookup_session: BeadIssueLookupSession,
) -> AgentFamilyPlanPreview | None:
    bead_type: Literal["phase", "task"]
    if issue.issue_type is IssueType.PHASE:
        bead_type = "phase"
    elif issue.issue_type is IssueType.TASK:
        bead_type = "task"
    else:
        return None
    parent_title = _parent_title_for_issue(
        issue,
        member,
        lookup_session=lookup_session,
    )
    return agent_family_plan_preview_from_bead(
        bead_type=bead_type,
        title=issue.title,
        parent_title=parent_title,
        size=normalize_phase_size(issue.size),
    )


def _parent_title_for_issue(
    issue: Issue,
    member: _FamilyPlanMember,
    *,
    lookup_session: BeadIssueLookupSession,
) -> str | None:
    if issue.issue_type is not IssueType.PHASE:
        return None
    parent_id = (issue.parent_id or member.epic_bead_id or "").strip()
    if not parent_id or parent_id == issue.id:
        return None
    try:
        parent = lookup_bead_issue(
            parent_id,
            project_name=member.project_name,
            workspace_dir=member.workspace_dir,
            lookup_session=lookup_session,
        )
    except Exception:
        return None
    if parent is None:
        return None
    title = (parent.title or "").strip()
    return title or None


def _fallback_title(members: Sequence[_FamilyPlanMember]) -> str:
    from sase.ace.tui._agent_completion_prompt import prompt_snippet

    for member in members:
        raw = member.raw_prompt_snippet
        if not raw:
            continue
        try:
            snippet = prompt_snippet(raw, humanize=False)
        except Exception:
            continue
        usable = _usable_prompt_snippet(snippet)
        if usable:
            return usable
    return ""


def _usable_prompt_snippet(snippet: str) -> str:
    """Drop leftover VCS tags/directives so the fallback is real prompt text."""
    cleaned = _LEFTOVER_HASH_REF_RE.sub("", snippet, count=1).strip()
    if not cleaned or cleaned.startswith(("%", "#")):
        return ""
    return cleaned


def _member_from_record(record: Any) -> _FamilyPlanMember:
    meta = getattr(record, "agent_meta", None)
    done = getattr(record, "done", None)
    plan_marker = getattr(record, "plan_path", None)
    archived = _first_str(
        getattr(plan_marker, "plan_path", None) if plan_marker is not None else None,
        getattr(done, "plan_path", None) if done is not None else None,
    )
    return _FamilyPlanMember(
        artifact_dir=str(record.artifact_dir),
        timestamp=str(getattr(record, "timestamp", "") or ""),
        plan_path=_optional_str(getattr(meta, "plan_path", None) if meta else None),
        archived_plan_path=archived,
        sdd_plan_path=_optional_str(
            getattr(meta, "sdd_plan_path", None) if meta else None
        ),
        epic_plan_ref=_optional_str(
            getattr(meta, "epic_plan_ref", None) if meta else None
        ),
        epic_bead_id=_optional_str(
            getattr(meta, "epic_bead_id", None) if meta else None
        ),
        phase_bead_id=_optional_str(
            getattr(meta, "phase_bead_id", None) if meta else None
        ),
        raw_prompt_snippet=_optional_str(getattr(record, "raw_prompt_snippet", None)),
        workspace_dir=_first_str(
            getattr(meta, "workspace_dir", None) if meta else None,
            getattr(done, "workspace_dir", None) if done is not None else None,
        ),
        project_name=_optional_str(getattr(record, "project_name", None)),
        workspace_num=getattr(meta, "workspace_num", None) if meta else None,
    )


def _first_str(*values: object) -> str | None:
    for value in values:
        text = _optional_str(value)
        if text is not None:
            return text
    return None


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


__all__ = [
    "FamilyPlanPreviewResult",
    "enrich_catalog_families",
]
