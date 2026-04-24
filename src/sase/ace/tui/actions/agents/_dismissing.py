"""Agent dismissal methods for the ace TUI app."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec

from ._killing_utils import (
    delete_agent_artifacts,
    dismiss_notifications_for_agent,
    dismiss_notifications_for_agents,
    find_workflow_workspace_from_running_field,
)

log = logging.getLogger(__name__)
AgentIdentity = tuple["AgentType", str, str | None]


class AgentDismissingMixin:
    """Mixin providing agent dismissal methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    # ChangeSpec state
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: str

    # Agent state
    _agents: list[Agent]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _pinned_agents: set[tuple[AgentType, str, str | None]]
    _agents_with_children: list[Agent]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]]

    def _apply_dismissal_in_memory(self, agents: Iterable[Agent]) -> None:
        """Update in-memory agent state after a dismiss without a disk reload.

        Removes the dismissed agents (and workflow-child steps when the
        dismissed agent is a workflow parent) from the cached unfiltered
        agent list, appends them to ``_dismissed_agent_objects`` for
        same-session revive, and re-runs the in-memory filter pipeline.
        """
        from ...models.agent import AgentType

        agents_list = list(agents)
        if not agents_list:
            self._refilter_agents()  # type: ignore[attr-defined]
            return

        removed: list[Agent] = list(agents_list)
        removed_identities: set[tuple[AgentType, str, str | None]] = {
            a.identity for a in agents_list
        }

        # Include workflow child steps when dismissing a workflow parent
        for agent in agents_list:
            if (
                agent.agent_type == AgentType.WORKFLOW
                and not agent.is_workflow_child
                and agent.raw_suffix is not None
            ):
                for step in self._agents_with_children:
                    if (
                        step.is_workflow_child
                        and step.parent_timestamp == agent.raw_suffix
                        and step.parent_workflow == agent.workflow
                        and step.identity not in removed_identities
                    ):
                        removed.append(step)
                        removed_identities.add(step.identity)

        # Remove from cached unfiltered list
        self._agents_with_children = [
            a
            for a in self._agents_with_children
            if a.identity not in removed_identities
        ]

        # Append to dismissed objects list for same-session revive (dedupe by identity)
        existing_identities = {a.identity for a in self._dismissed_agent_objects}
        for agent in removed:
            if agent.identity not in existing_identities:
                self._dismissed_agent_objects.append(agent)
                existing_identities.add(agent.identity)

        self._refilter_agents()  # type: ignore[attr-defined]

    def _save_agent_bundle(self, agent: Agent) -> None:
        """Save a serialized bundle of agent data before artifact deletion.

        Bundles are used to populate the revive modal after TUI restart.
        ChangeSpec-loaded agents are skipped since they persist via .gp file fields.
        """
        from ....dismissed_agents import save_dismissed_bundle

        # Skip ChangeSpec-loaded agents — they persist via .gp file fields
        if agent._from_changespec:
            return

        save_dismissed_bundle(agent)

        # Also bundle workflow child steps when dismissing a parent.
        # Use _agents_with_children (unfiltered by fold state) so children
        # are included even when the workflow is collapsed.
        if not agent.is_workflow_child and agent.raw_suffix:
            for step in self._agents_with_children:
                if (
                    step.is_workflow_child
                    and step.parent_timestamp == agent.raw_suffix
                    and step.parent_workflow == agent.workflow
                ):
                    save_dismissed_bundle(step)

    def _persist_dismissed_agent(
        self, identity: tuple[AgentType, str, str | None]
    ) -> None:
        """Add an agent identity to the dismissed set and save to disk."""
        from ....dismissed_agents import save_dismissed_agents

        self._dismissed_agents.add(identity)
        save_dismissed_agents(self._dismissed_agents)

    def _collect_dismissal_identities(self, agents: list[Agent]) -> set[AgentIdentity]:
        """Return identities hidden immediately after dismissing agents."""
        from ...models.agent import AgentType

        identities = {a.identity for a in agents}
        for agent in agents:
            if (
                agent.agent_type == AgentType.WORKFLOW
                and not agent.is_workflow_child
                and agent.raw_suffix is not None
            ):
                for step in self._agents_with_children:
                    if (
                        step.is_workflow_child
                        and step.parent_timestamp == agent.raw_suffix
                        and step.parent_workflow == agent.workflow
                    ):
                        identities.add(step.identity)
        return identities

    def _append_dismissed_agent_objects(
        self, agents: list[Agent], identities: set[AgentIdentity]
    ) -> None:
        """Track dismissed objects for same-session revive."""
        if not hasattr(self, "_dismissed_agent_objects"):
            return
        existing = {a.identity for a in self._dismissed_agent_objects}
        for agent in self._agents_with_children:
            if agent.identity in identities and agent.identity not in existing:
                self._dismissed_agent_objects.append(agent)
                existing.add(agent.identity)
        for agent in agents:
            if agent.identity not in existing:
                self._dismissed_agent_objects.append(agent)
                existing.add(agent.identity)

    def _dismiss_all_done_agents(self) -> None:
        """Dismiss all done/failed agents after user confirmation."""
        from ._core import DISMISSABLE_STATUSES

        dismissable = [
            a
            for a in self._agents
            if a.status in DISMISSABLE_STATUSES
            and a.raw_suffix is not None
            and a.identity not in self._pinned_agents
        ]

        if not dismissable:
            self.notify("No agents to dismiss", severity="warning")  # type: ignore[attr-defined]
            return

        # Build description similar to ConfirmKillModal format
        count = len(dismissable)
        s = "s" if count != 1 else ""
        desc_parts = [f"Count: {count} agent{s}"]
        for agent in dismissable:
            name = agent.display_name
            suffix = f" @{agent.agent_name}" if agent.agent_name else ""
            desc_parts.append(f"  {name}{suffix}")
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmDismissAllModal

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self._do_dismiss_all(dismissable)

        self.push_screen(ConfirmDismissAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

    def _do_dismiss_all(self, agents: list[Agent]) -> None:
        """Perform batch dismissal of done/failed agents."""
        from ...models.agent import AgentType
        from ....dismissed_agents import save_dismissed_agents

        for agent in agents:
            dismiss_notifications_for_agent(agent)
            self._agent_status_overrides.pop(agent.identity, None)
            self._agent_pre_question_status.pop(agent.identity, None)

            # Save bundle before deleting artifacts (for revive support)
            self._save_agent_bundle(agent)

            # Handle workspace release for workflow agents
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

            # Delete artifact files
            delete_agent_artifacts(agent.artifacts_dir or agent.get_artifacts_dir())

            # Track dismissal
            self._dismissed_agents.add(agent.identity)

            # Also dismiss children for workflow parents
            if agent.agent_type == AgentType.WORKFLOW and not agent.is_workflow_child:
                for step in self._agents_with_children:
                    if (
                        step.is_workflow_child
                        and step.parent_timestamp == agent.raw_suffix
                        and step.parent_workflow == agent.workflow
                    ):
                        self._dismissed_agents.add(step.identity)

        # Batch persist and reload
        save_dismissed_agents(self._dismissed_agents)
        self._refresh_notification_count()  # type: ignore[attr-defined]

        count = len(agents)
        s = "s" if count != 1 else ""
        self.notify(f"Dismissed {count} agent{s}")  # type: ignore[attr-defined]
        self._apply_dismissal_in_memory(agents)

    def _dismiss_done_agent(self, agent: Agent) -> None:
        """Dismiss a DONE or completed workflow agent.

        Updates the UI optimistically and schedules filesystem/project-file
        cleanup in an async worker.

        Args:
            agent: The DONE or completed agent to dismiss.
        """
        from ...models.agent import AgentType

        if agent.raw_suffix is None:
            self.notify("Cannot dismiss agent: no timestamp", severity="error")  # type: ignore[attr-defined]
            return

        agents_with_children_snapshot = list(self._agents_with_children)
        identities = self._collect_dismissal_identities([agent])
        for identity in identities:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)
        self._dismissed_agents.update(identities)
        self._append_dismissed_agent_objects([agent], identities)

        if agent.agent_type == AgentType.WORKFLOW:
            self.notify(f"Dismissed workflow {agent.workflow}")  # type: ignore[attr-defined]
        else:
            self.notify(f"Dismissed agent for {agent.cl_name}")  # type: ignore[attr-defined]
        self._apply_dismissal_in_memory([agent])
        self.call_later(  # type: ignore[attr-defined]
            self._run_dismiss_persistence_async,
            agent,
            set(self._dismissed_agents),
            agents_with_children_snapshot,
        )

    async def _run_dismiss_persistence_async(
        self,
        agent: Agent,
        dismissed_snapshot: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
    ) -> None:
        """Persist single-agent dismiss side effects in a worker thread."""
        identity = agent.identity
        if identity in self._dismiss_persistence_inflight:
            return
        self._dismiss_persistence_inflight.add(identity)

        started = time.perf_counter()
        try:
            await asyncio.to_thread(
                persist_single_dismiss_transaction,
                agent,
                dismissed_snapshot,
                agents_with_children_snapshot,
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Dismiss cleanup failed for {agent.display_name}: {exc}",
                severity="error",
            )
        finally:
            self._dismiss_persistence_inflight.discard(identity)
            log.debug(
                "agent dismiss persistence: identity=%s elapsed=%.3fs",
                identity,
                time.perf_counter() - started,
            )
            self._refresh_notification_count()  # type: ignore[attr-defined]
            self._schedule_agents_async_refresh()  # type: ignore[attr-defined]


def persist_single_dismiss_transaction(
    agent: Agent,
    dismissed_snapshot: set[AgentIdentity],
    agents_with_children_snapshot: list[Agent],
) -> None:
    """Persist all side effects for one optimistic dismiss operation."""
    from ....dismissed_agents import save_dismissed_agents

    persist_dismiss_side_effects(agent, agents_with_children_snapshot)
    dismiss_notifications_for_agents(
        _agents_related_to_dismissal(agent, agents_with_children_snapshot)
    )
    save_dismissed_agents(dismissed_snapshot)


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


def _agents_related_to_dismissal(
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
