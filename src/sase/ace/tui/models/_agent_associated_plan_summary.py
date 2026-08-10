"""Plan-file loading and summary construction for agent plan enrichment."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sase.core.artifact_file_helpers import select_canonical_plan_path

from ._agent_associated_plan_paths import display_plan_path
from ._agent_associated_plan_types import (
    AssociatedPlanPhaseAvailability,
    AssociatedPlanSummary,
    AssociatedPlanTier,
    AuthoredPlanTier,
    PlanFileMetadata,
)
from .agent import Agent

PlanMetadataLoader = Callable[[Path], PlanFileMetadata]
PlanReferenceResolver = Callable[[Agent, str, str], Path]


def build_associated_plan_summary(
    agent: Agent,
    plan_path: Path,
    metadata: PlanFileMetadata,
    *,
    committed: bool | None,
    display_committed: bool,
    known_epic: bool,
) -> AssociatedPlanSummary:
    """Build the render-ready summary shared by agent and phase plans."""
    availability = _phase_availability(
        agent,
        metadata,
        known_epic=known_epic,
    )
    return AssociatedPlanSummary(
        title=metadata.title,
        goal=metadata.goal,
        authored_tier=metadata.authored_tier,
        effective_tier=_effective_tier(
            agent,
            metadata.authored_tier,
            committed=committed,
        ),
        actual_path=str(plan_path),
        display_path=display_plan_path(
            plan_path,
            agent,
            committed=display_committed,
        ),
        committed=committed,
        exists=metadata.exists,
        readable=metadata.readable,
        frontmatter_readable=metadata.frontmatter_readable,
        phase_availability=availability,
        phases=(metadata.phases if availability == "available" else ()),
        validation_ok=metadata.validation_ok,
        validation_diagnostics=metadata.validation_diagnostics,
    )


def direct_plan_reference(agent: Agent) -> str | None:
    archived_path = agent.archived_plan_path
    if (
        archived_path is None
        and agent.plan_path
        and agent.plan_path != agent.sdd_plan_path
    ):
        archived_path = agent.plan_path
    return select_canonical_plan_path(
        archived_plan_path=archived_path,
        sdd_plan_path=agent.sdd_plan_path,
        plan_committed=agent.plan_committed,
        plan_action=agent.plan_action,
    )


def _phase_availability(
    agent: Agent,
    metadata: PlanFileMetadata,
    *,
    known_epic: bool,
) -> AssociatedPlanPhaseAvailability:
    if metadata.authored_tier == "tale":
        return "not-applicable"
    if metadata.authored_tier == "epic":
        return metadata.phase_availability
    if (
        known_epic
        or agent.plan_action == "epic"
        or agent.epic_bead_id
        or agent.phase_bead_id
    ):
        return "unavailable"
    return "not-applicable"


def effective_commit_state(agent: Agent) -> bool | None:
    if agent.plan_committed is not None:
        return agent.plan_committed
    if agent.plan_action in {"commit", "tale", "epic"}:
        return True
    return None


def resolve_authored_plan(
    agent: Agent,
    *,
    parent_path: Path | None,
    load_plan_metadata: PlanMetadataLoader,
    resolve_plan_reference: PlanReferenceResolver,
) -> tuple[AssociatedPlanSummary | None, Path | None]:
    """Return a PLAN only when the agent has a distinct authored artifact."""
    archived_reference = agent.archived_plan_path
    if (
        archived_reference is None
        and agent.plan_path
        and agent.plan_path != agent.sdd_plan_path
    ):
        archived_reference = agent.plan_path

    archived_path = _resolve_distinct_authored_reference(
        agent,
        "authored-archive",
        archived_reference,
        parent_path=parent_path,
        resolve_plan_reference=resolve_plan_reference,
    )
    sdd_path = _resolve_distinct_authored_reference(
        agent,
        "authored-sdd",
        agent.sdd_plan_path,
        parent_path=parent_path,
        resolve_plan_reference=resolve_plan_reference,
    )
    has_handoff_evidence = bool(
        archived_path is not None
        or agent.plan_action is not None
        or (
            sdd_path is not None
            and agent.plan_committed is not None
            and agent.agent_family_role in {"code", "plan", "feedback"}
        )
    )
    if not has_handoff_evidence:
        return None, None
    if archived_path is None and sdd_path is None:
        return None, None

    selected_path: Path
    if archived_path is not None and sdd_path is not None:
        selected_reference = select_canonical_plan_path(
            archived_plan_path=str(archived_path),
            sdd_plan_path=str(sdd_path),
            plan_committed=agent.plan_committed,
            plan_action=agent.plan_action,
        )
        selected_path = Path(selected_reference or archived_path)
    else:
        only_path = archived_path or sdd_path
        assert only_path is not None
        selected_path = only_path

    selected_is_sdd = sdd_path is not None and _same_plan_path(
        selected_path,
        sdd_path,
    )
    if selected_is_sdd:
        committed = effective_commit_state(agent)
    elif agent.plan_committed is False or agent.plan_action == "approve":
        committed = False
    elif sdd_path is None:
        # A distinct archive with no authored SDD handoff is a submitted plan;
        # the inherited parent epic's commit bit does not apply to it.
        committed = False
    else:
        committed = effective_commit_state(agent)

    metadata = load_plan_metadata(selected_path)
    summary = build_associated_plan_summary(
        agent,
        selected_path,
        metadata,
        committed=committed,
        display_committed=committed is True,
        known_epic=False,
    )
    return summary, selected_path


def _resolve_distinct_authored_reference(
    agent: Agent,
    source: str,
    reference: str | None,
    *,
    parent_path: Path | None,
    resolve_plan_reference: PlanReferenceResolver,
) -> Path | None:
    if not reference:
        return None
    path = resolve_plan_reference(agent, source, reference)
    if parent_path is not None and _same_plan_path(path, parent_path):
        return None
    return path


def _same_plan_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve(strict=False) == right.expanduser().resolve(
        strict=False
    )


def _effective_tier(
    agent: Agent,
    authored_tier: AuthoredPlanTier | None,
    *,
    committed: bool | None = None,
) -> AssociatedPlanTier | None:
    if agent.plan_action == "approve":
        return "plan"
    if agent.plan_action in {"commit", "tale"}:
        return "tale"
    if agent.plan_action == "epic":
        return "epic"
    if agent.plan_action is not None:
        return None
    if committed is None:
        committed = agent.plan_committed
    if committed is False:
        return "plan"
    if authored_tier == "epic":
        return "epic"
    if authored_tier == "tale":
        return "tale"
    if committed is True:
        return "tale"
    return None
