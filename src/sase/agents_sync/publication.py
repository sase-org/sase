"""Public API for targeted and full owner-sharded hood publication."""

from __future__ import annotations

from pathlib import Path

from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.inventory import (
    ProjectHoodInventory,
    build_project_hood_inventory,
)
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_planning import plan_hoods
from sase.agents_sync.v2_io import apply_payload_atomic
from sase.agents_sync.v2_models import V2PublicationCounts
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    agent_local_hood,
    normalize_agent_archive_name,
    normalize_owned_agent_name,
)
from sase.sase_agent import SaseAgentRef, sase_agent_ref_for_name


def publish_agent_hood(
    target: ProjectTarget,
    repo_root: Path,
    committing_agent: str,
    *,
    identity: AgentIdentitySnapshot | None = None,
    inventory: ProjectHoodInventory | None = None,
    git_runner: GitRunner = run_git,
) -> V2PublicationCounts:
    """Refresh exactly the committing sase agent's complete top-level local hood.

    ``committing_agent`` names a sase agent: either a solo agent, which is
    also a run, or a family container, which never is. Both spellings are
    accepted deliberately, and a concrete agent-shell name is still tolerated
    for legacy callers.
    """

    snapshot = identity or AgentIdentitySnapshot.current()
    owner = _owner(snapshot)
    local_name = normalize_agent_archive_name(
        normalize_owned_agent_name(committing_agent, snapshot)
    )
    project_inventory = inventory or build_project_hood_inventory(
        target, snapshot, git_runner=git_runner
    )
    agent_ref: SaseAgentRef = sase_agent_ref_for_name(local_name, snapshot)
    hood = agent_local_hood(agent_ref.local_name)
    if agent_ref.is_family:
        # A family sase agent is a container, not a run, so only its hood
        # decides whether there is anything to publish.
        publishable = bool(project_inventory.hood_runs(hood))
    else:
        publishable = any(
            run.local_name == local_name for run in project_inventory.runs
        ) or bool(project_inventory.hood_runs(hood))
    if not publishable:
        # Load-bearing message: publication queue retirement matches on it.
        raise AgentsSyncFormatError(f"hood {hood!r} has no publishable runs")
    return _publish_hoods(
        target,
        repo_root,
        project_inventory,
        (hood,),
        owner,
    )


def reconcile_agent_hoods(
    target: ProjectTarget,
    repo_root: Path,
    *,
    identity: AgentIdentitySnapshot | None = None,
    inventory: ProjectHoodInventory | None = None,
    git_runner: GitRunner = run_git,
) -> V2PublicationCounts:
    """Publish every locally owned hood with a primary-repository commit."""

    snapshot = identity or AgentIdentitySnapshot.current()
    owner = _owner(snapshot)
    project_inventory = inventory or build_project_hood_inventory(
        target, snapshot, git_runner=git_runner
    )
    return _publish_hoods(
        target,
        repo_root,
        project_inventory,
        project_inventory.eligible_hoods(),
        owner,
    )


def _publish_hoods(
    target: ProjectTarget,
    repo_root: Path,
    inventory: ProjectHoodInventory,
    hoods: tuple[str, ...],
    owner: AgentOwnerIdentity,
) -> V2PublicationCounts:
    payload, counts = plan_hoods(
        target,
        repo_root,
        inventory,
        hoods,
        owner,
    )
    apply_payload_atomic(repo_root, payload)
    return counts


def _owner(identity: AgentIdentitySnapshot) -> AgentOwnerIdentity:
    if identity.owner is None:
        raise AgentsSyncFormatError("v2 publication requires an owner identity")
    return identity.owner


# Explicit aliases for callers that prefer the plan's terminology.
publish_targeted_hood = publish_agent_hood
reconcile_all_hoods = reconcile_agent_hoods


__all__ = [
    "publish_agent_hood",
    "publish_targeted_hood",
    "reconcile_agent_hoods",
    "reconcile_all_hoods",
]
