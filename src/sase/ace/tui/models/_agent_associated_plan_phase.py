"""Phase-specific associated-plan and bead enrichment."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sase.agent.bead_display import (
    BeadIssueLookupSession,
    derive_agent_bead_id_from_name,
    normalize_bead_text,
)
from sase.bead.phase_description import generated_phase_description

from ._agent_associated_plan_paths import display_plan_path
from ._agent_associated_plan_summary import (
    build_associated_plan_summary,
    direct_plan_reference,
    resolve_authored_plan,
)
from ._agent_associated_plan_types import (
    AgentPlanEnrichment,
    PhaseBeadSummary,
    PlanFileMetadata,
    ResolvedPlanAssociation,
)
from .agent import Agent

ParentAssociationResolver = Callable[
    [Agent, str, BeadIssueLookupSession | None],
    ResolvedPlanAssociation,
]
IssueAssociationResolver = ParentAssociationResolver
PlanMetadataLoader = Callable[[Path], PlanFileMetadata]
PlanReferenceResolver = Callable[[Agent, str, str], Path]


def resolve_phase_plan_enrichment(
    agent: Agent,
    *,
    lookup_session: BeadIssueLookupSession | None,
    resolve_parent_association: ParentAssociationResolver,
    resolve_issue_association: IssueAssociationResolver,
    load_plan_metadata: PlanMetadataLoader,
    resolve_plan_reference: PlanReferenceResolver,
    parent_association: ResolvedPlanAssociation | None = None,
) -> AgentPlanEnrichment:
    """Resolve a phase's parent BEAD and authored PLAN independently."""
    phase_bead_id = agent.phase_bead_id or _derived_phase_bead_id(agent)
    epic_bead_id = agent.epic_bead_id
    parent_reference = agent.epic_plan_ref
    parent_path: Path | None = None
    notes: str | None = None
    created_at = ""

    if not parent_reference and agent.agent_family_role == "phase":
        # Damaged pre-field phase rows carried the parent epic in the generic
        # plan slots. Preserve their no-bead-lookup privacy behavior while
        # modern rows use the explicit parent reference above.
        parent_reference = direct_plan_reference(agent)

    if parent_reference:
        parent_path = resolve_plan_reference(
            agent,
            "parent-direct",
            parent_reference,
        )
        if agent.phase_bead_id and agent.epic_plan_ref:
            issue_association = resolve_issue_association(
                agent,
                agent.phase_bead_id,
                lookup_session,
            )
            notes = _phase_notes_from_association(
                issue_association,
                agent.phase_bead_id,
            )
            created_at = _phase_created_at_from_association(
                issue_association,
                agent.phase_bead_id,
            )
    else:
        bead_id = phase_bead_id or derive_agent_bead_id_from_name(
            agent.presented_agent_name or agent.agent_name
        )
        if parent_association is None and bead_id is not None:
            parent_association = resolve_parent_association(
                agent,
                bead_id,
                lookup_session,
            )
        if parent_association is not None:
            parent_path = parent_association.path
            parent_reference = parent_association.plan_reference
            epic_bead_id = parent_association.epic_bead_id or epic_bead_id
            phase_bead_id = parent_association.phase_bead_id or phase_bead_id
            notes = _phase_notes_from_association(parent_association, phase_bead_id)
            created_at = _phase_created_at_from_association(
                parent_association,
                phase_bead_id,
            )

    phase_bead: PhaseBeadSummary | None = None
    if phase_bead_id is not None:
        if parent_path is None:
            phase_bead = unavailable_phase_bead(
                phase_bead_id,
                plan_reference=parent_reference,
                notes=notes,
                created_at=created_at,
            )
        else:
            parent_metadata = load_plan_metadata(parent_path)
            phase_bead = phase_bead_summary(
                parent_metadata,
                agent=agent,
                epic_bead_id=epic_bead_id,
                phase_bead_id=phase_bead_id,
                plan_reference=parent_reference or str(parent_path),
                plan_path=parent_path,
                notes=notes,
                created_at=created_at,
            )

    associated_plan, authored_path = resolve_authored_plan(
        agent,
        parent_path=parent_path,
        load_plan_metadata=load_plan_metadata,
        resolve_plan_reference=resolve_plan_reference,
    )
    return AgentPlanEnrichment(
        role="phase",
        phase_bead=phase_bead,
        associated_plan=associated_plan,
        resolved_plan_paths=_resolved_plan_paths(parent_path, authored_path),
    )


def _resolved_plan_paths(*paths: Path | None) -> tuple[str, ...]:
    seen: set[Path] = set()
    resolved: list[str] = []
    for path in paths:
        if path is None:
            continue
        normalized = path.expanduser().resolve(strict=False)
        if normalized in seen:
            continue
        seen.add(normalized)
        resolved.append(str(path))
    return tuple(resolved)


def phase_bead_summary(
    metadata: PlanFileMetadata,
    *,
    agent: Agent,
    epic_bead_id: str | None,
    phase_bead_id: str,
    plan_reference: str,
    plan_path: Path,
    notes: str | None = None,
    created_at: str = "",
) -> PhaseBeadSummary:
    """Build one render-ready selected-phase summary from validated order."""
    summary = unavailable_phase_bead(
        phase_bead_id,
        agent=agent,
        metadata=metadata,
        plan_reference=plan_reference,
        plan_path=plan_path,
        notes=notes,
        created_at=created_at,
    )
    phase_index = _phase_index(epic_bead_id, phase_bead_id)
    if (
        phase_index is None
        or metadata.phase_availability != "available"
        or phase_index >= len(metadata.phases)
    ):
        return summary

    phase = metadata.phases[phase_index]
    description = phase.description or generated_phase_description(
        plan_reference,
        phase.id,
    )
    normalized = normalize_bead_text(description)
    return PhaseBeadSummary(
        id=phase_bead_id,
        phase_title=normalize_bead_text(phase.title) or None,
        description=normalized or None,
        actual_plan_path=summary.actual_plan_path,
        display_plan_path=summary.display_plan_path,
        plan_exists=summary.plan_exists,
        plan_readable=summary.plan_readable,
        epic_title=metadata.title,
        size=phase.size,
        created_at=summary.created_at,
        bead_type="phase",
        notes=summary.notes,
    )


def unavailable_phase_bead(
    phase_bead_id: str,
    *,
    agent: Agent | None = None,
    metadata: PlanFileMetadata | None = None,
    plan_reference: str | None = None,
    plan_path: Path | None = None,
    notes: str | None = None,
    created_at: str = "",
) -> PhaseBeadSummary:
    """Return a phase identity with honest optional-field fallbacks."""
    actual_path = str(plan_path) if plan_path is not None else None
    display_path = _phase_display_plan_path(
        plan_reference,
        plan_path=plan_path,
        agent=agent,
    )
    return PhaseBeadSummary(
        id=phase_bead_id,
        phase_title=None,
        description=None,
        actual_plan_path=actual_path,
        display_plan_path=display_path,
        plan_exists=metadata.exists if metadata is not None else False,
        plan_readable=metadata.readable if metadata is not None else False,
        epic_title=None,
        size=None,
        created_at=created_at,
        bead_type="phase",
        notes=notes,
    )


def _phase_notes_from_association(
    association: ResolvedPlanAssociation,
    phase_bead_id: str | None,
) -> str | None:
    if (
        phase_bead_id is None
        or association.role != "phase"
        or association.phase_bead_id != phase_bead_id
    ):
        return None
    return association.notes


def _phase_created_at_from_association(
    association: ResolvedPlanAssociation,
    phase_bead_id: str | None,
) -> str:
    if (
        phase_bead_id is None
        or association.role != "phase"
        or association.phase_bead_id != phase_bead_id
    ):
        return ""
    return association.created_at


def _phase_display_plan_path(
    reference: str | None,
    *,
    plan_path: Path | None,
    agent: Agent | None,
) -> str | None:
    """Keep canonical relative references while resolving only navigation paths."""
    if reference:
        raw_reference = Path(reference).expanduser()
        if not raw_reference.is_absolute():
            return raw_reference.as_posix()
    if plan_path is not None and agent is not None:
        return display_plan_path(plan_path, agent, committed=True)
    return None


def _phase_index(epic_bead_id: str | None, phase_bead_id: str) -> int | None:
    if not epic_bead_id:
        return None
    prefix = f"{epic_bead_id}."
    if not phase_bead_id.startswith(prefix):
        return None
    ordinal = phase_bead_id[len(prefix) :]
    if not ordinal.isdigit():
        return None
    value = int(ordinal)
    return value - 1 if value > 0 else None


def _derived_phase_bead_id(agent: Agent) -> str | None:
    """Recover only a structurally trustworthy child ID from a phase name."""
    candidate = derive_agent_bead_id_from_name(
        agent.presented_agent_name or agent.agent_name
    )
    if candidate is None:
        return None
    if agent.epic_bead_id:
        return (
            candidate
            if _phase_index(agent.epic_bead_id, candidate) is not None
            else None
        )
    _, separator, ordinal = candidate.rpartition(".")
    return candidate if separator and ordinal.isdigit() and int(ordinal) > 0 else None
