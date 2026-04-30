"""Persistence (filesystem/project-file) side effects for agent kills."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

from ._dismissing import (
    persist_cleanup_side_effect_intents,
    persist_dismiss_side_effects,
)
from ._killing_utils import (
    delete_agent_artifacts,
    dismiss_notifications_for_agents,
    find_workflow_workspace_from_running_field,
)

KillKind = Literal["running", "hook", "mentor", "crs", "workflow"]
AgentIdentity = tuple["AgentType", str, str | None]


@dataclass(frozen=True)
class BulkKillItem:
    agent: Agent
    kind: KillKind
    identities: set[AgentIdentity]


def persist_kill_side_effects(
    agent: Agent,
    kind: KillKind,
    agents_with_children_snapshot: list[Agent],
) -> None:
    """Apply filesystem/project-file side effects for a kill operation."""
    if kind == "running":
        _persist_running_kill(agent)
    elif kind == "hook":
        _persist_hook_kill(agent)
    elif kind == "mentor":
        _persist_mentor_kill(agent)
    elif kind == "crs":
        _persist_crs_kill(agent)
    elif kind == "workflow":
        _persist_workflow_kill(agent, agents_with_children_snapshot)


def persist_bulk_kill_side_effects(
    kill_items: list[BulkKillItem],
    dismissable: list[Agent],
    dismissed_snapshot: set[AgentIdentity],
    agents_with_children_snapshot: list[Agent],
    cleanup_plan: object | None = None,
) -> None:
    """Apply filesystem/project-file side effects for a bulk kill operation."""
    from ....dismissed_agents import save_dismissed_agents

    consumed_intents = persist_cleanup_side_effect_intents(
        cleanup_plan,
        agents_with_children_snapshot,
    )
    for item in kill_items:
        if consumed_intents and item.kind in {"running", "workflow"}:
            continue
        persist_kill_side_effects(
            item.agent,
            item.kind,
            agents_with_children_snapshot,
        )
    if not consumed_intents:
        for agent in dismissable:
            persist_dismiss_side_effects(agent, agents_with_children_snapshot)

    if not consumed_intents and (kill_items or dismissable):
        dismiss_notifications_for_agents(
            [item.agent for item in kill_items] + list(dismissable)
        )
    save_dismissed_agents(dismissed_snapshot)


def _persist_running_kill(agent: Agent) -> None:
    from sase.running_field import release_workspace

    if agent.workspace_num is not None:
        release_workspace(
            agent.project_file,
            agent.workspace_num,
            agent.workflow,
            agent.cl_name,
        )


def _persist_hook_kill(agent: Agent) -> None:
    if agent.pid is None:
        return
    from ....changespec import parse_project_file
    from ....hooks import update_changespec_hooks_field
    from ....hooks.processes import mark_hook_agents_as_killed
    from sase.core.agent_cleanup_execution import mark_hook_agents_as_killed_rust

    changespecs = parse_project_file(agent.project_file)
    for cs in changespecs:
        if cs.name == agent.cl_name and cs.hooks:
            matched_suffixes: list[str] = []
            killed_hook_agents = []
            for hook in cs.hooks:
                if hook.status_lines:
                    for sl in hook.status_lines:
                        if (
                            sl.suffix_type == "running_agent"
                            and sl.suffix == agent.raw_suffix
                        ):
                            if sl.suffix is not None:
                                matched_suffixes.append(sl.suffix)
                            killed_hook_agents.append((hook, sl, agent.pid))

            if killed_hook_agents:
                updated_hooks = mark_hook_agents_as_killed_rust(
                    cs.hooks, matched_suffixes
                ) or mark_hook_agents_as_killed(cs.hooks, killed_hook_agents)
                update_changespec_hooks_field(
                    agent.project_file, agent.cl_name, updated_hooks
                )
            break


def _persist_mentor_kill(agent: Agent) -> None:
    if agent.pid is None:
        return
    from ....changespec import parse_project_file
    from ....hooks.processes import mark_mentor_agents_as_killed
    from ....mentors import update_changespec_mentors_field
    from sase.core.agent_cleanup_execution import mark_mentor_agents_as_killed_rust

    changespecs = parse_project_file(agent.project_file)
    for cs in changespecs:
        if cs.name == agent.cl_name and cs.mentors:
            matched_suffixes: list[str] = []
            killed_mentor_agents = []
            for entry in cs.mentors:
                if entry.status_lines:
                    for sl in entry.status_lines:
                        if (
                            sl.suffix_type == "running_agent"
                            and sl.suffix == agent.raw_suffix
                        ):
                            if sl.suffix is not None:
                                matched_suffixes.append(sl.suffix)
                            killed_mentor_agents.append((entry, sl, agent.pid))

            if killed_mentor_agents:
                updated_mentors = mark_mentor_agents_as_killed_rust(
                    cs.mentors, matched_suffixes
                ) or mark_mentor_agents_as_killed(cs.mentors, killed_mentor_agents)
                update_changespec_mentors_field(
                    agent.project_file, agent.cl_name, updated_mentors
                )
            break


def _persist_crs_kill(agent: Agent) -> None:
    if agent.pid is None:
        return
    from ....changespec import parse_project_file
    from ....comments import update_changespec_comments_field
    from ....comments.operations import mark_comment_agents_as_killed
    from sase.core.agent_cleanup_execution import mark_comment_agents_as_killed_rust

    changespecs = parse_project_file(agent.project_file)
    for cs in changespecs:
        if cs.name == agent.cl_name and cs.comments:
            matched_suffixes: list[str] = []
            killed_comment_agents = []
            for comment in cs.comments:
                if (
                    comment.suffix_type == "running_agent"
                    and comment.suffix == agent.raw_suffix
                ):
                    if comment.suffix is not None:
                        matched_suffixes.append(comment.suffix)
                    killed_comment_agents.append((comment, agent.pid))

            if killed_comment_agents:
                updated_comments = mark_comment_agents_as_killed_rust(
                    cs.comments, matched_suffixes
                ) or mark_comment_agents_as_killed(cs.comments, killed_comment_agents)
                update_changespec_comments_field(
                    agent.project_file, agent.cl_name, updated_comments
                )
            break


def _persist_workflow_kill(
    agent: Agent, agents_with_children_snapshot: list[Agent]
) -> None:
    from ....dismissed_agents import save_dismissed_bundle
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

    if not agent._from_changespec:
        save_dismissed_bundle(agent)
    delete_agent_artifacts(agent.artifacts_dir or agent.get_artifacts_dir())
    if not agent.is_workflow_child and agent.raw_suffix:
        for step in agents_with_children_snapshot:
            if (
                step.is_workflow_child
                and step.parent_timestamp == agent.raw_suffix
                and step.parent_workflow == agent.workflow
            ):
                if not step._from_changespec:
                    save_dismissed_bundle(step)
                delete_agent_artifacts(step.artifacts_dir or step.get_artifacts_dir())
