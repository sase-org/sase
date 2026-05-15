"""Persistence side effects for agent dismissal."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._dismiss_cleanup import agent_wire_identity, wire_identity_key
from ._killing_utils import (
    delete_agent_artifacts,
    dismiss_notifications_for_agents,
    find_workflow_workspace_from_running_field,
)

if TYPE_CHECKING:
    from ...models import Agent


def persist_cleanup_side_effect_intents(
    cleanup_plan: object | None,
    agents_with_children_snapshot: list[Agent],
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
        if agent is not None and not agent._from_changespec:
            save_dismissed_bundle(agent)

    for intent in getattr(side_effects, "workspace_release_requests", ()):
        workspace = intent.workspace
        workflow = intent.workflow
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
            release_workspace(intent.project_file, workspace, f"workflow({workflow})")
        else:
            release_workspace(
                intent.project_file,
                workspace,
                workflow if agent is None else agent.workflow,
                intent.cl_name if agent is None else agent.cl_name,
            )

    for intent in getattr(side_effects, "artifact_delete_paths", ()):
        delete_agent_artifacts(intent.artifacts_dir)

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


def persist_dismiss_side_effects(
    agent: Agent,
    agents_with_children_snapshot: list[Agent],
) -> None:
    """Apply filesystem side effects for one asynchronously dismissed agent."""
    from ...models.agent import AgentType
    from ....dismissed_agents import save_dismissed_bundle

    if not agent._from_changespec:
        save_dismissed_bundle(agent)
        if not agent.is_workflow_child and agent.raw_suffix:
            for step in agents_with_children_snapshot:
                if (
                    step.is_workflow_child
                    and step.parent_timestamp == agent.raw_suffix
                    and step.parent_workflow == agent.workflow
                    and not step._from_changespec
                ):
                    save_dismissed_bundle(step)

    if agent.agent_type == AgentType.WORKFLOW:
        from sase.running_field import release_workspace

        workflow_name = agent.workflow
        if agent.is_workflow_child and agent.parent_workflow:
            workflow_name = agent.parent_workflow
        if workflow_name is not None:
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
            if workspace_num is not None:
                release_workspace(
                    agent.project_file,
                    workspace_num,
                    f"workflow({workflow_name})",
                )

    delete_agent_artifacts(agent.artifacts_dir or agent.get_artifacts_dir())
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
                delete_agent_artifacts(step.artifacts_dir or step.get_artifacts_dir())


def agents_related_to_dismissal(
    agent: Agent,
    agents_with_children_snapshot: list[Agent],
) -> list[Agent]:
    """Return the primary agent plus workflow children dismissed with it."""
    from ...models.agent import AgentType

    agents = [agent]
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
