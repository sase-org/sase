"""Persistence side effects for agent dismissal."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from ._dismiss_cleanup import agent_wire_identity, wire_identity_key
from ._clan_cleanup import clan_members_for_container
from ._killing_utils import (
    delete_agent_artifacts,
    dismiss_notifications_for_agents,
    find_workflow_workspace_from_running_field,
)
from sase.core.agent_artifact_index_lifecycle import (
    delete_agent_artifact_index_artifacts,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

log = logging.getLogger(__name__)


def add_dismissed_batch(
    added: Iterable[tuple[AgentType, str, str | None]],
) -> set[tuple[AgentType, str, str | None]] | None:
    """Add one batch's identities to the on-disk dismissed index.

    The write merges under a file lock, so concurrent procs, runners, and
    TUIs never lose each other's dismissals. Returns the resulting on-disk
    set for the artifact-index sync, or None when the write failed: a failed
    publish must not stop the rest of the cleanup transaction.
    """
    from ....dismissed_agents import add_dismissed_agents

    try:
        return add_dismissed_agents(added)
    except Exception:
        log.exception("Failed to add identities to the dismissed-agents index")
        return None


def _release_held_workspace_claims(
    project_file: str,
    artifacts_timestamp: str | None,
    cl_name: str | None,
) -> int:
    """Release dead workspace claims belonging to one dismissed agent run."""
    if not project_file or not artifacts_timestamp:
        return 0

    from sase.ace.hooks.processes import is_process_running
    from sase.running_field import get_claimed_workspaces, release_workspace

    expected_cl_name = cl_name if cl_name and cl_name != "unknown" else None
    released = 0
    for claim in get_claimed_workspaces(project_file):
        if claim.artifacts_timestamp != artifacts_timestamp:
            continue
        if expected_cl_name is not None and claim.cl_name != expected_cl_name:
            continue
        if is_process_running(claim.pid):
            continue
        result = release_workspace(
            project_file,
            claim.workspace_num,
            claim.workflow,
            claim.cl_name,
            caller_tag="dismiss",
        )
        if result.success:
            released += 1
    return released


def persist_cleanup_side_effect_intents(
    cleanup_plan: object | None,
    agents_with_children_snapshot: list[Agent],
    *,
    register_expected_deletion: Callable[[str | None], None] | None = None,
) -> bool:
    """Execute host-owned side effects described by a cleanup intent plan."""
    side_effects = getattr(cleanup_plan, "side_effects", None)
    if side_effects is None:
        return False

    has_intents = any(
        getattr(side_effects, attr, ())
        for attr in (
            "bundle_save_candidates",
            "artifact_delete_paths",
            "workspace_release_requests",
            "notification_dismiss_candidates",
        )
    )
    if not has_intents:
        return False

    from ....dismissed_agents import save_dismissed_bundle
    from sase.running_field import release_workspace

    by_identity = {
        agent_wire_identity(agent): agent for agent in agents_with_children_snapshot
    }

    for intent in getattr(side_effects, "bundle_save_candidates", ()):
        agent = by_identity.get(wire_identity_key(intent.identity))
        if agent is not None and not agent._from_patch:
            save_dismissed_bundle(agent)

    for intent in getattr(side_effects, "workspace_release_requests", ()):
        workspace = intent.workspace
        workflow = intent.workflow
        if getattr(intent, "lookup_timestamp", False):
            _release_held_workspace_claims(
                intent.project_file,
                getattr(intent, "artifacts_timestamp", None),
                intent.cl_name,
            )
            continue
        if intent.lookup_workflow and workflow is not None:
            workspace = find_workflow_workspace_from_running_field(
                intent.project_file,
                workflow,
                intent.cl_name,
            )
        if workspace is None:
            continue
        agent = by_identity.get(wire_identity_key(intent.identity))
        if (
            workflow is not None
            and agent is not None
            and agent.agent_type.value == "workflow"
        ):
            release_workspace(
                intent.project_file,
                workspace,
                f"workflow({workflow})",
                caller_tag="dismiss",
            )
        else:
            release_workspace(
                intent.project_file,
                workspace,
                workflow if agent is None else agent.workflow,
                intent.cl_name if agent is None else agent.cl_name,
                caller_tag="dismiss",
            )

    artifact_delete_paths = [
        intent.artifacts_dir
        for intent in getattr(side_effects, "artifact_delete_paths", ())
    ]
    delete_agent_artifact_index_artifacts(artifact_delete_paths)
    for artifacts_dir in artifact_delete_paths:
        if register_expected_deletion is None:
            delete_agent_artifacts(artifacts_dir)
        else:
            delete_agent_artifacts(
                artifacts_dir,
                before_delete=register_expected_deletion,
            )

    notification_identities = {
        wire_identity_key(intent.identity)
        for intent in getattr(side_effects, "notification_dismiss_candidates", ())
    }
    notification_agents = [
        agent
        for agent in agents_with_children_snapshot
        if agent_wire_identity(agent) in notification_identities
    ]
    if notification_agents:
        dismiss_notifications_for_agents(notification_agents)
    return True


def _save_dismissed_bundles_for(
    agent: Agent,
    agents_with_children_snapshot: list[Agent],
) -> None:
    from ....dismissed_agents import save_dismissed_bundle

    if agent._from_patch:
        return
    save_dismissed_bundle(agent)
    for member in clan_members_for_container(
        agent,
        agents_with_children_snapshot,
    ):
        if not member._from_patch:
            save_dismissed_bundle(member)
    if agent.is_workflow_child or not agent.raw_suffix:
        return
    for step in agents_with_children_snapshot:
        if (
            step.is_workflow_child
            and step.parent_timestamp == agent.raw_suffix
            and step.parent_workflow == agent.workflow
            and not step._from_patch
        ):
            save_dismissed_bundle(step)


def _release_workspace_for(agent: Agent) -> None:
    from ...models.agent import AgentType

    if (
        agent.agent_type in {AgentType.RUNNING, AgentType.WORKFLOW}
        and not agent.is_workflow_child
    ):
        _release_held_workspace_claims(
            agent.project_file,
            agent.raw_suffix,
            agent.cl_name,
        )

    if agent.agent_type != AgentType.WORKFLOW:
        return
    from sase.running_field import release_workspace

    workflow_name = agent.workflow
    if agent.is_workflow_child and agent.parent_workflow:
        workflow_name = agent.parent_workflow
    if workflow_name is None:
        return
    workspace_num = agent.workspace_num
    if workspace_num is None:
        lookup_cl_name = None
        if not agent.is_workflow_child and agent.cl_name != "unknown":
            lookup_cl_name = agent.cl_name
        workspace_num = find_workflow_workspace_from_running_field(
            agent.project_file,
            workflow_name,
            lookup_cl_name,
        )
    if workspace_num is None:
        return
    release_workspace(
        agent.project_file,
        workspace_num,
        f"workflow({workflow_name})",
        caller_tag="dismiss",
    )


def _artifact_delete_paths_for(
    agent: Agent,
    agents_with_children_snapshot: list[Agent],
) -> list[str | None]:
    from ...models.agent import AgentType

    paths: list[str | None] = [agent.artifacts_dir or agent.get_artifacts_dir()]
    paths.extend(
        member.artifacts_dir or member.get_artifacts_dir()
        for member in clan_members_for_container(
            agent,
            agents_with_children_snapshot,
        )
    )
    if (
        agent.agent_type == AgentType.WORKFLOW
        and not agent.is_workflow_child
        and agent.raw_suffix
    ):
        for step in agents_with_children_snapshot:
            if (
                step.is_workflow_child
                and step.parent_timestamp == agent.raw_suffix
                and step.parent_workflow == agent.workflow
            ):
                paths.append(step.artifacts_dir or step.get_artifacts_dir())
    return paths


def persist_dismiss_side_effects(
    agent: Agent,
    agents_with_children_snapshot: list[Agent],
    *,
    register_expected_deletion: Callable[[str | None], None] | None = None,
) -> None:
    """Apply filesystem side effects for one asynchronously dismissed agent."""
    _save_dismissed_bundles_for(agent, agents_with_children_snapshot)
    _release_workspace_for(agent)

    artifact_delete_paths = _artifact_delete_paths_for(
        agent, agents_with_children_snapshot
    )
    delete_agent_artifact_index_artifacts(artifact_delete_paths)
    for artifacts_dir in artifact_delete_paths:
        if register_expected_deletion is None:
            delete_agent_artifacts(artifacts_dir)
        else:
            delete_agent_artifacts(
                artifacts_dir,
                before_delete=register_expected_deletion,
            )


def persist_bulk_dismiss_side_effects(
    agents: list[Agent],
    agents_with_children_snapshot: list[Agent],
    *,
    register_expected_deletion: Callable[[str | None], None] | None = None,
) -> None:
    """Batched fallback for bulk dismiss when Rust cleanup intents are absent.

    Saves bundles per agent (still requires per-bundle disk writes), then
    issues *one* artifact-index delete for all paths in the batch instead of
    one connection per agent. Filesystem rmtree work runs last so the SQLite
    index stays consistent if a single rmtree fails.
    """
    artifact_delete_paths: list[str | None] = []
    seen_paths: set[str] = set()
    for agent in agents:
        _save_dismissed_bundles_for(agent, agents_with_children_snapshot)
        _release_workspace_for(agent)
        for path in _artifact_delete_paths_for(agent, agents_with_children_snapshot):
            key = str(path) if path is not None else ""
            if key in seen_paths:
                continue
            seen_paths.add(key)
            artifact_delete_paths.append(path)

    delete_agent_artifact_index_artifacts(artifact_delete_paths)
    for artifacts_dir in artifact_delete_paths:
        if register_expected_deletion is None:
            delete_agent_artifacts(artifacts_dir)
        else:
            delete_agent_artifacts(
                artifacts_dir,
                before_delete=register_expected_deletion,
            )


def agents_related_to_dismissal(
    agent: Agent,
    agents_with_children_snapshot: list[Agent],
) -> list[Agent]:
    """Return the primary agent plus session/workflow children dismissed with it.

    Same-identity rows are the same agent in another incarnation: a FAILED or
    DONE row dismissed while its live STARTING twin is still on disk. The
    in-memory removal and the session tombstone already hide by identity, so
    the durable safety net must see the live twin or its tree keeps running.
    """
    from ...models.agent import AgentType

    agents = [agent]
    seen = {id(agent)}
    for row in agents_with_children_snapshot:
        if id(row) in seen:
            continue
        # Snapshots from older callers can carry bare identity tuples; only
        # real rows participate in same-identity matching.
        if getattr(row, "identity", None) != agent.identity:
            continue
        seen.add(id(row))
        agents.append(row)
    for member in clan_members_for_container(agent, agents_with_children_snapshot):
        if id(member) not in seen:
            seen.add(id(member))
            agents.append(member)
    if (
        agent.agent_type == AgentType.WORKFLOW
        and not agent.is_workflow_child
        and agent.raw_suffix
    ):
        agents.extend(
            step
            for step in agents_with_children_snapshot
            if step.is_workflow_child
            and step.parent_timestamp == agent.raw_suffix
            and step.parent_workflow == agent.workflow
        )
    return agents
