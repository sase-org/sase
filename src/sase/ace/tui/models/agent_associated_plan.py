"""Associated-plan resolution for deferred Agents-tab detail enrichment.

This module is the stable import facade. Value types, caches, filesystem path
handling, plan summaries, and phase handling live in focused sibling modules;
role-aware orchestration and bead lookup compatibility remain here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, cast

from sase.agent.bead_display import (
    BeadIssueLookupSession,
    derive_agent_bead_id_from_name,
    lookup_bead_issue,
    normalize_bead_text,
)
from sase.bead.flag_fields import flag_fields, is_flag_bead
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bead_type_presentation import BeadTypeValue
from sase.phase_size_presentation import normalize_phase_size
from sase.sdd.plan_validate import validate_plan

from ._agent_associated_plan_cache import (
    _CACHE_MISS,
    _PLAN_ASSOCIATION_CACHE,
    _PLAN_FILE_CACHE,
    PlanAssociationCache as _PlanAssociationCache,
    PlanFileCache as _PlanFileCache,
)
from ._agent_associated_plan_paths import (
    agent_project_name as _agent_project_name,
    association_key as _association_key,
    resolve_plan_reference as _resolve_plan_reference,
)
from ._agent_associated_plan_phase import (
    phase_bead_summary as _phase_bead_summary,
    resolve_phase_plan_enrichment as _resolve_phase_plan_enrichment,
    unavailable_phase_bead as _unavailable_phase_bead,
)
from ._agent_associated_plan_summary import (
    build_associated_plan_summary as _build_associated_plan_summary,
    direct_plan_reference as _direct_plan_reference,
    effective_commit_state as _effective_commit_state,
    resolve_authored_plan as _resolve_authored_plan,
)
from ._agent_associated_plan_types import (
    AgentPlanRole,
    AssociatedPlanPhaseAvailability as AssociatedPlanPhaseAvailability,
    AssociatedPlanPhaseSummary as AssociatedPlanPhaseSummary,
    AssociatedPlanSummary as AssociatedPlanSummary,
    AssociatedPlanTier as AssociatedPlanTier,
    AuthoredPlanTier as AuthoredPlanTier,
    BeadSummary as BeadSummary,
    AgentPlanEnrichment as _AgentPlanEnrichment,
    _InitialAgentPlanRole,
    PhaseBeadSummary as PhaseBeadSummary,
    PlanFileMetadata as _PlanFileMetadata,
    ResolvedPlanAssociation as _ResolvedPlanAssociation,
    normalize_bead_notes as _normalize_bead_notes,
)
from .agent import Agent


def associated_plan_cache_key(agent: Agent) -> tuple[object, ...]:
    """Return the memory-only inputs that can change plan enrichment."""
    return (
        agent.plan_path,
        agent.archived_plan_path,
        agent.sdd_plan_path,
        agent.epic_plan_ref,
        agent.plan_committed,
        agent.plan_action,
        agent.epic_bead_id,
        agent.phase_bead_id,
        agent.agent_family_role,
        agent.agent_name,
        agent.project_file,
        agent.workspace_dir,
        agent.effective_workspace_num,
    )


def resolve_agent_plan_enrichment(
    agent: Agent,
    *,
    lookup_session: BeadIssueLookupSession | None = None,
) -> _AgentPlanEnrichment:
    """Resolve role-specific plan metadata for the selected agent once.

    This function may touch plan, workspace, and bead storage. Callers must
    keep it inside the existing deferred detail-header enrichment worker.
    Modern phase structure takes an explicit parent-epic reference; optional
    notes may still be enriched from the exact local phase bead. Legacy rows
    retain the bounded local compatibility lookup for parent-plan recovery.
    """
    initial_role = _initial_agent_plan_role(agent)
    role: AgentPlanRole = "phase" if initial_role == "ambiguous" else initial_role
    association: _ResolvedPlanAssociation | None = None
    if initial_role == "phase":
        return _resolve_phase_plan_enrichment(
            agent,
            lookup_session=lookup_session,
            resolve_parent_association=_phase_parent_association,
            resolve_issue_association=_phase_issue_association,
            load_plan_metadata=_load_plan_metadata,
            resolve_plan_reference=_resolve_cached_reference,
        )
    if initial_role == "land" and not _is_explicit_land_role(agent):
        bead_id = derive_agent_bead_id_from_name(
            agent.presented_agent_name or agent.agent_name
        )
        if bead_id is not None:
            association = _cached_bead_plan_association(
                agent,
                bead_id,
                source="bead-role",
                lookup_session=lookup_session,
            )
        if association is not None and association.role == "task":
            return _task_plan_enrichment(agent, association)
        if association is not None and association.role == "flag":
            return _flag_bead_enrichment(association)
    if initial_role == "ambiguous":
        bead_id = derive_agent_bead_id_from_name(
            agent.presented_agent_name or agent.agent_name
        )
        if bead_id is not None:
            association = _cached_bead_plan_association(
                agent,
                bead_id,
                source="bead-role",
                lookup_session=lookup_session,
            )
        if association is not None and association.role == "task":
            return _task_plan_enrichment(agent, association)
        if association is not None and association.role == "flag":
            return _flag_bead_enrichment(association)
        if association is None or association.role != "land":
            if association is None or association.path is None:
                # A confirmed legacy phase without an epic-plan association
                # keeps the compact historical ``Bead:`` row. Only promote
                # it into the structured BEAD lane once a parent plan can be
                # resolved; unconfirmed dotted names remain invisible.
                return _AgentPlanEnrichment("phase", None, None, ())
            return _resolve_phase_plan_enrichment(
                agent,
                lookup_session=lookup_session,
                resolve_parent_association=_phase_parent_association,
                resolve_issue_association=_phase_issue_association,
                load_plan_metadata=_load_plan_metadata,
                resolve_plan_reference=_resolve_cached_reference,
                parent_association=association,
            )
        role = "land"

    reference = _direct_plan_reference(agent)
    plan_path: Path | None
    source = "direct"
    known_epic = False
    if reference:
        plan_path = _resolve_cached_reference(agent, source, reference)
    else:
        source = "bead"
        bead_id = _agent_bead_id(agent)
        if bead_id is None:
            return _AgentPlanEnrichment(role, None, None, ())
        if association is None:
            association = _cached_bead_plan_association(
                agent,
                bead_id,
                source=source,
                lookup_session=lookup_session,
            )
        plan_path = association.path
        known_epic = association.known_epic
        if association.role == "task":
            return _task_plan_enrichment(agent, association)
        if initial_role in {"ordinary", "ambiguous"} and association.role is not None:
            role = association.role

    if plan_path is None:
        # Legacy rows still use the generic confirmation cache for bead-only
        # display. Returning a bare id here would let ambient/stale bead-store
        # state overwrite a richer confirmed description (or surface a cold
        # candidate). Explicit modern phases returned above remain phase-local
        # and authoritative even without a usable plan reference.
        phase_bead = None
        if role == "phase" and association is not None:
            phase_id = association.phase_bead_id
            if phase_id is not None:
                phase_bead = _unavailable_phase_bead(phase_id)
        return _AgentPlanEnrichment(role, phase_bead, None, ())

    if role == "phase":
        metadata = _load_plan_metadata(plan_path)
        epic_bead_id = association.epic_bead_id if association is not None else None
        phase_bead_id = association.phase_bead_id if association is not None else None
        plan_reference = (
            reference
            or (association.plan_reference if association is not None else None)
            or str(plan_path)
        )
        phase_bead = (
            _phase_bead_summary(
                metadata,
                agent=agent,
                epic_bead_id=epic_bead_id,
                phase_bead_id=phase_bead_id,
                plan_reference=plan_reference,
                plan_path=plan_path,
            )
            if phase_bead_id
            else None
        )
        return _AgentPlanEnrichment(
            role="phase",
            phase_bead=phase_bead,
            associated_plan=None,
            resolved_plan_paths=(str(plan_path),),
        )

    metadata = _load_plan_metadata(plan_path)
    committed = _effective_commit_state(agent)
    summary = _build_associated_plan_summary(
        agent,
        plan_path,
        metadata,
        committed=committed,
        display_committed=committed is True or source == "bead",
        known_epic=known_epic,
    )
    return _AgentPlanEnrichment(
        role=role,
        phase_bead=None,
        associated_plan=summary,
        resolved_plan_paths=(str(plan_path),),
    )


def _task_plan_enrichment(
    agent: Agent,
    association: _ResolvedPlanAssociation,
) -> _AgentPlanEnrichment:
    """Pair a task BEAD with a plan the task agent itself authored.

    A task bead never owns a plan, so the only PLAN a task row may show is the
    handoff artifact this agent produced. ``parent_path=None`` keeps the shared
    resolver's evidence gate intact: without a distinct archive, a plan action,
    or a committed SDD handoff, no plan file is read and no lane appears.
    """
    summary, path = _resolve_authored_plan(
        agent,
        parent_path=None,
        load_plan_metadata=_load_plan_metadata,
        resolve_plan_reference=_resolve_cached_reference,
    )
    return _AgentPlanEnrichment(
        "task",
        association.bead_summary,
        summary,
        () if path is None else (str(path),),
    )


def _flag_bead_enrichment(
    association: _ResolvedPlanAssociation,
) -> _AgentPlanEnrichment:
    """Project a standalone flag bead into the BEAD lane."""
    return _AgentPlanEnrichment(
        "flag",
        association.bead_summary,
        None,
        (),
    )


def _initial_agent_plan_role(agent: Agent) -> _InitialAgentPlanRole:
    if agent.phase_bead_id or agent.agent_family_role == "phase":
        return "phase"

    presented_name = agent.presented_agent_name or agent.agent_name
    derived_bead_id = derive_agent_bead_id_from_name(presented_name)
    if agent.epic_bead_id:
        if derived_bead_id == agent.epic_bead_id:
            return "land"
        return "author"

    if presented_name and presented_name.endswith(".land"):
        return "land"
    if derived_bead_id is not None:
        # Child phase IDs append a numeric component. A nested epic ID can
        # have the same shape, so legacy dotted names stay ambiguous until a
        # bounded issue lookup confirms whether the exact bead is epic/phase.
        return "ambiguous" if "." in derived_bead_id else "land"
    if agent.plan_action == "epic":
        return "author"
    return "ordinary"


def _is_explicit_land_role(agent: Agent) -> bool:
    """Return whether land identity is explicit rather than name-inferred."""
    if agent.epic_bead_id:
        return True
    presented_name = agent.presented_agent_name or agent.agent_name
    return bool(presented_name and presented_name.endswith(".land"))


def _load_plan_metadata(path: Path) -> _PlanFileMetadata:
    return _PLAN_FILE_CACHE.get(
        path,
        is_readable=lambda candidate: os.access(candidate, os.R_OK),
        validate=validate_plan,
    )


def _resolve_cached_reference(agent: Agent, source: str, reference: str) -> Path:
    key = _association_key(agent, source, reference)
    cached = _PLAN_ASSOCIATION_CACHE.get(key)
    if cached is _CACHE_MISS:
        path = _resolve_plan_reference(reference, agent)
        _PLAN_ASSOCIATION_CACHE.set(key, _ResolvedPlanAssociation(path))
        return path
    assert isinstance(cached, _ResolvedPlanAssociation)
    assert cached.path is not None
    return cached.path


def _phase_parent_association(
    agent: Agent,
    bead_id: str,
    lookup_session: BeadIssueLookupSession | None,
) -> _ResolvedPlanAssociation:
    return _cached_bead_plan_association(
        agent,
        bead_id,
        source="bead-parent",
        lookup_session=lookup_session,
    )


def _phase_issue_association(
    agent: Agent,
    bead_id: str,
    lookup_session: BeadIssueLookupSession | None,
) -> _ResolvedPlanAssociation:
    key = _association_key(agent, "bead-issue", bead_id)
    cached = _PLAN_ASSOCIATION_CACHE.get(key)
    if cached is not _CACHE_MISS:
        assert isinstance(cached, _ResolvedPlanAssociation)
        return cached

    if lookup_session is None:
        with BeadIssueLookupSession() as owned_session:
            association = _resolve_bead_issue_association(
                agent,
                bead_id,
                lookup_session=owned_session,
            )
    else:
        association = _resolve_bead_issue_association(
            agent,
            bead_id,
            lookup_session=lookup_session,
        )
    _PLAN_ASSOCIATION_CACHE.set(key, association)
    return association


def _cached_bead_plan_association(
    agent: Agent,
    bead_id: str,
    *,
    source: str,
    lookup_session: BeadIssueLookupSession | None,
) -> _ResolvedPlanAssociation:
    key = _association_key(agent, source, bead_id)
    cached = _PLAN_ASSOCIATION_CACHE.get(key)
    if cached is not _CACHE_MISS:
        assert isinstance(cached, _ResolvedPlanAssociation)
        return cached

    if lookup_session is None:
        with BeadIssueLookupSession() as owned_session:
            association = _resolve_bead_plan_association(
                agent,
                bead_id,
                lookup_session=owned_session,
            )
    else:
        association = _resolve_bead_plan_association(
            agent,
            bead_id,
            lookup_session=lookup_session,
        )
    _PLAN_ASSOCIATION_CACHE.set(key, association)
    return association


def _resolve_bead_plan_association(
    agent: Agent,
    bead_id: str,
    *,
    lookup_session: BeadIssueLookupSession,
) -> _ResolvedPlanAssociation:
    issue = _lookup_issue(agent, bead_id, lookup_session=lookup_session)
    if issue is None:
        return _ResolvedPlanAssociation(None)
    notes = _normalize_bead_notes(issue.notes)
    is_phase = issue.issue_type is IssueType.PHASE
    is_epic = issue.issue_type is IssueType.PLAN and issue.tier is BeadTier.EPIC
    is_flag = is_flag_bead(issue)
    is_task = issue.issue_type is IssueType.TASK and not is_flag
    role: Literal["phase", "task", "flag", "land"] | None = (
        "phase"
        if is_phase
        else "flag"
        if is_flag
        else "task"
        if is_task
        else "land"
        if is_epic
        else None
    )
    epic_bead_id = issue.parent_id if is_phase else (issue.id if is_epic else None)
    phase_bead_id = issue.id if is_phase else None
    known_epic = is_phase or is_epic
    bead_summary = _plan_free_bead_summary(issue) if is_task or is_flag else None
    design = issue.design.strip()
    if not design and issue.parent_id:
        parent = _lookup_issue(agent, issue.parent_id, lookup_session=lookup_session)
        if parent is not None:
            design = parent.design.strip()
            known_epic = known_epic or parent.tier is BeadTier.EPIC
            if parent.tier is BeadTier.EPIC:
                epic_bead_id = parent.id
    if not design:
        return _ResolvedPlanAssociation(
            None,
            known_epic=known_epic,
            role=role,
            epic_bead_id=epic_bead_id,
            phase_bead_id=phase_bead_id,
            created_at=issue.created_at if is_phase else "",
            bead_summary=bead_summary,
            notes=notes,
        )
    return _ResolvedPlanAssociation(
        _resolve_plan_reference(design, agent),
        known_epic=known_epic,
        role=role,
        plan_reference=design,
        epic_bead_id=epic_bead_id,
        phase_bead_id=phase_bead_id,
        created_at=issue.created_at if is_phase else "",
        bead_summary=bead_summary,
        notes=notes,
    )


def _resolve_bead_issue_association(
    agent: Agent,
    bead_id: str,
    *,
    lookup_session: BeadIssueLookupSession,
) -> _ResolvedPlanAssociation:
    issue = _lookup_issue(agent, bead_id, lookup_session=lookup_session)
    if issue is None:
        return _ResolvedPlanAssociation(None)
    is_phase = issue.issue_type is IssueType.PHASE
    is_epic = issue.issue_type is IssueType.PLAN and issue.tier is BeadTier.EPIC
    is_flag = is_flag_bead(issue)
    is_task = issue.issue_type is IssueType.TASK and not is_flag
    role: Literal["phase", "task", "flag", "land"] | None = (
        "phase"
        if is_phase
        else "flag"
        if is_flag
        else "task"
        if is_task
        else "land"
        if is_epic
        else None
    )
    return _ResolvedPlanAssociation(
        None,
        known_epic=is_phase or is_epic,
        role=role,
        epic_bead_id=issue.parent_id if is_phase else (issue.id if is_epic else None),
        phase_bead_id=issue.id if is_phase else None,
        created_at=issue.created_at if is_phase else "",
        bead_summary=_plan_free_bead_summary(issue) if is_task or is_flag else None,
        notes=_normalize_bead_notes(issue.notes),
    )


def _plan_free_bead_summary(issue: Issue) -> BeadSummary:
    """Project one task or flag issue into render-ready BEAD metadata."""
    fields = flag_fields(issue)
    bead_type: BeadTypeValue = (
        "flag" if is_flag_bead(issue) else cast(BeadTypeValue, issue.issue_type.value)
    )
    return BeadSummary(
        id=issue.id,
        phase_title=normalize_bead_text(issue.title) or None,
        description=normalize_bead_text(issue.description) or None,
        actual_plan_path=None,
        display_plan_path=None,
        plan_exists=False,
        plan_readable=False,
        epic_title=None,
        size=normalize_phase_size(issue.size),
        created_at=issue.created_at,
        bead_type=bead_type,
        notes=_normalize_bead_notes(issue.notes),
        plus_one_evidence=tuple(issue.plus_one_evidence),
        flag_key=None if fields is None else fields.key,
        flag_remove_by_date=None if fields is None else fields.remove_by_date,
        flag_remove_by_release=None if fields is None else fields.remove_by_release,
        task_type=issue.task_type,
    )


def _lookup_issue(
    agent: Agent,
    bead_id: str,
    *,
    lookup_session: BeadIssueLookupSession,
) -> Issue | None:
    return lookup_bead_issue(
        bead_id,
        project_name=_agent_project_name(agent),
        workspace_dir=agent.workspace_dir,
        local_only=True,
        lookup_session=lookup_session,
    )


def _agent_bead_id(agent: Agent) -> str | None:
    return (
        agent.phase_bead_id
        or agent.epic_bead_id
        or derive_agent_bead_id_from_name(
            agent.presented_agent_name or agent.agent_name
        )
    )
