"""Agent dismissal methods for the ace TUI app."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec

from ._killing_utils import (
    delete_agent_artifacts,
    dismiss_notifications_for_agents,
    find_workflow_workspace_from_running_field,
)

log = logging.getLogger(__name__)
AgentIdentity = tuple["AgentType", str, str | None]


def _completion_date_for(agent: Agent) -> datetime:
    """Return the best-known completion date for *agent*.

    Used to derive the ``YYmmdd`` dismissal prefix. Falls back through
    ``stop_time`` → ``start_time`` → parsed ``raw_suffix`` → ``now()`` so
    partially-populated bundles still get a deterministic date.
    """
    if agent.stop_time is not None:
        return agent.stop_time
    if agent.start_time is not None:
        return agent.start_time
    if agent.raw_suffix:
        try:
            return datetime.strptime(agent.raw_suffix[:14], "%Y%m%d%H%M%S")
        except ValueError:
            pass
    return datetime.now()


def _base_for_dismissal(agent: Agent) -> str:
    """Return a non-empty base name to use when prefixing *agent*."""
    from sase.agent.names import strip_dismissed_prefix

    if agent.agent_name:
        return strip_dismissed_prefix(agent.agent_name)
    if agent.cl_name and agent.cl_name != "unknown":
        return agent.cl_name
    if agent.raw_suffix:
        return agent.raw_suffix
    return "agent"


def _apply_dismissal_rename(
    agent: Agent,
    agents_with_children_snapshot: Iterable[Agent],
    *,
    taken: set[str] | None = None,
) -> dict[str, str]:
    """Mutate *agent* (and its workflow children) to carry dismissed names.

    The parent's :attr:`Agent.agent_name` becomes ``YYmmdd.<base>``, where
    *base* is the parent's existing name when one was set, else its
    ``cl_name``/``raw_suffix`` so unnamed dismissals still produce a
    non-empty prefixed name. Workflow children that already carry a name
    are reprefixed with the same date so wait/resume references remain
    consistent. When *taken* is provided it is updated in place with newly
    allocated names so subsequent dismissals in the same batch do not
    collide; when ``None``, the allocator scans persisted state on its own.

    Returns a ``{old_name: new_name}`` map for every rename performed so
    callers can rewrite dependent wait/resume references in one pass.
    Unnamed agents that gained a dismissed name for the first time are
    excluded from the map — there are no preexisting references to migrate.
    """
    from ...models.agent import AgentType
    from sase.agent.names import (
        add_dismissed_prefix,
        allocate_dismissed_name,
    )

    name_map: dict[str, str] = {}
    completion_date = _completion_date_for(agent)
    base = _base_for_dismissal(agent)
    new_name = allocate_dismissed_name(base, completion_date, taken=taken)
    old_name = agent.agent_name
    agent.agent_name = new_name
    if taken is not None:
        taken.add(new_name)
    if old_name and old_name != new_name:
        name_map[old_name] = new_name

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
                and step.agent_name
            ):
                old_step = step.agent_name
                step.agent_name = add_dismissed_prefix(step.agent_name, completion_date)
                if old_step != step.agent_name:
                    name_map[old_step] = step.agent_name
    return name_map


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

        # Capture the pre-mutation visible-row anchor so focus lands on the
        # agent visually below the dismissed one.
        prior_pos = (
            self._capture_focused_visible_pos()  # type: ignore[attr-defined]
            if hasattr(self, "_capture_focused_visible_pos")
            else None
        )

        agents_list = list(agents)
        if not agents_list:
            self._refilter_agents(prior_pos=prior_pos)  # type: ignore[attr-defined]
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

        # Try the incremental row-removal fast path before mutating
        # ``_agents`` / ``_agents_with_children`` so panel widgets can
        # still locate the dismissed identities in their cached slices.
        fast_path = (
            hasattr(self, "_try_remove_agent_rows")
            and self._try_remove_agent_rows(removed_identities)  # type: ignore[attr-defined]
        )

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

        if fast_path:
            self._apply_dismissal_in_memory_fast_finish(
                removed_identities, prior_pos=prior_pos
            )
            return

        self._refilter_agents(prior_pos=prior_pos)  # type: ignore[attr-defined]

    def _apply_dismissal_in_memory_fast_finish(
        self,
        removed_identities: set[tuple[AgentType, str, str | None]],
        *,
        prior_pos: int | None,
    ) -> None:
        """Finish a fast-path dismissal: mutate ``_agents``, restore focus,
        and refresh non-list widgets without rebuilding the option list.
        """
        self._agents = [a for a in self._agents if a.identity not in removed_identities]
        if hasattr(self, "_invalidate_agent_panel_cache"):
            self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        if hasattr(self, "_restore_focus_after_removal"):
            self._restore_focus_after_removal(prior_pos)  # type: ignore[attr-defined]
        if hasattr(self, "_refresh_tab_bar_agent_counts"):
            self._refresh_tab_bar_agent_counts()  # type: ignore[attr-defined]
        if self.current_tab == "agents":
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=False, defer_detail=True
            )

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
            for a in self._agents_in_focused_panel()  # type: ignore[attr-defined]
            if a.status in DISMISSABLE_STATUSES and a.raw_suffix is not None
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
        """Perform batch dismissal of done/failed agents.

        Updates the UI optimistically (in-memory list, dismissed set,
        notifications) and schedules every disk side effect — bundle saves,
        artifact deletion, workspace release, ``dismissed.json`` write — on
        a worker thread. The Textual event loop returns to the user before
        any persistence runs.
        """
        from ...models.agent import AgentType

        if not agents:
            return

        agents_with_children_snapshot = list(self._agents_with_children)

        from sase.agent.names import collect_dismissed_taken_names

        allocated_names: set[str] = collect_dismissed_taken_names()
        name_map: dict[str, str] = {}
        for agent in agents:
            name_map.update(
                _apply_dismissal_rename(
                    agent,
                    agents_with_children_snapshot,
                    taken=allocated_names,
                )
            )

        for agent in agents:
            self._agent_status_overrides.pop(agent.identity, None)
            self._agent_pre_question_status.pop(agent.identity, None)
            self._dismissed_agents.add(agent.identity)
            if agent.agent_type == AgentType.WORKFLOW and not agent.is_workflow_child:
                for step in agents_with_children_snapshot:
                    if (
                        step.is_workflow_child
                        and step.parent_timestamp == agent.raw_suffix
                        and step.parent_workflow == agent.workflow
                    ):
                        self._dismissed_agents.add(step.identity)

        count = len(agents)
        s = "s" if count != 1 else ""
        self.notify(f"Dismissed {count} agent{s}")  # type: ignore[attr-defined]
        self._apply_dismissal_in_memory(agents)
        _apply_in_memory_reference_rewrites(self._agents_with_children, name_map)
        self._refresh_notification_count()  # type: ignore[attr-defined]

        self.call_later(  # type: ignore[attr-defined]
            self._run_bulk_dismiss_persistence_async,
            list(agents),
            set(self._dismissed_agents),
            agents_with_children_snapshot,
            name_map,
        )

    async def _run_bulk_dismiss_persistence_async(
        self,
        agents: list[Agent],
        dismissed_snapshot: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
        name_map: dict[str, str],
    ) -> None:
        """Persist a batch dismissal's filesystem side effects in a worker."""
        identities = {a.identity for a in agents}
        if identities & self._dismiss_persistence_inflight:
            return
        self._dismiss_persistence_inflight.update(identities)

        started = time.perf_counter()
        try:
            await asyncio.to_thread(
                persist_bulk_dismiss_transaction,
                agents,
                dismissed_snapshot,
                agents_with_children_snapshot,
                name_map,
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Bulk dismiss cleanup failed: {exc}",
                severity="error",
            )
            self._schedule_agents_async_refresh()  # type: ignore[attr-defined]
        finally:
            self._dismiss_persistence_inflight.difference_update(identities)
            log.debug(
                "bulk agent dismiss persistence: count=%d elapsed=%.3fs",
                len(agents),
                time.perf_counter() - started,
            )

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
        name_map = _apply_dismissal_rename(agent, agents_with_children_snapshot)
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
        _apply_in_memory_reference_rewrites(self._agents_with_children, name_map)
        self.call_later(  # type: ignore[attr-defined]
            self._run_dismiss_persistence_async,
            agent,
            set(self._dismissed_agents),
            agents_with_children_snapshot,
            name_map,
        )

    async def _run_dismiss_persistence_async(
        self,
        agent: Agent,
        dismissed_snapshot: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
        name_map: dict[str, str],
    ) -> None:
        """Persist single-agent dismiss side effects in a worker thread.

        On success, the optimistic in-memory state is already authoritative —
        the worker only writes to ``dismissed.json``, deletes artifact dirs,
        releases the workspace, removes notifications, and saves bundles.
        None of those mutate ``.gp`` files, so a post-persistence disk reload
        would only re-derive the state we already have. The reload is skipped
        and the main thread is freed for the next keystroke; concurrent edits
        from another sase process are picked up by the next periodic
        auto-refresh. On failure, the reload is retained as a recovery path
        so the UI re-syncs with whatever actually landed on disk.
        """
        identity = agent.identity
        if identity in self._dismiss_persistence_inflight:
            return
        self._dismiss_persistence_inflight.add(identity)

        started = time.perf_counter()
        success = True
        try:
            await asyncio.to_thread(
                persist_single_dismiss_transaction,
                agent,
                dismissed_snapshot,
                agents_with_children_snapshot,
                name_map,
            )
        except Exception as exc:
            success = False
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
            if success:
                await self._refresh_notification_count_async()  # type: ignore[attr-defined]
            else:
                self._refresh_notification_count()  # type: ignore[attr-defined]
                self._schedule_agents_async_refresh()  # type: ignore[attr-defined]


def persist_single_dismiss_transaction(
    agent: Agent,
    dismissed_snapshot: set[AgentIdentity],
    agents_with_children_snapshot: list[Agent],
    name_map: dict[str, str],
) -> None:
    """Persist all side effects for one optimistic dismiss operation."""
    from ....dismissed_agents import save_dismissed_agents
    from sase.agent.dismissed_name_rewrites import rewrite_dismissed_references

    rewrite_dismissed_references(name_map)
    persist_dismiss_side_effects(agent, agents_with_children_snapshot)
    dismiss_notifications_for_agents(
        _agents_related_to_dismissal(agent, agents_with_children_snapshot)
    )
    save_dismissed_agents(dismissed_snapshot)


def persist_bulk_dismiss_transaction(
    agents: list[Agent],
    dismissed_snapshot: set[AgentIdentity],
    agents_with_children_snapshot: list[Agent],
    name_map: dict[str, str],
) -> None:
    """Persist all side effects for an optimistic batch dismiss operation."""
    from ....dismissed_agents import save_dismissed_agents
    from sase.agent.dismissed_name_rewrites import rewrite_dismissed_references

    rewrite_dismissed_references(name_map)
    related: list[Agent] = []
    for agent in agents:
        persist_dismiss_side_effects(agent, agents_with_children_snapshot)
        related.extend(
            _agents_related_to_dismissal(agent, agents_with_children_snapshot)
        )
    if related:
        dismiss_notifications_for_agents(related)
    save_dismissed_agents(dismissed_snapshot)


def _apply_in_memory_reference_rewrites(
    agents: Iterable[Agent],
    name_map: dict[str, str],
) -> None:
    """Update each agent's ``waiting_for`` list using *name_map* in place."""
    if not name_map:
        return
    for agent in agents:
        if not agent.waiting_for:
            continue
        new_waiting = [name_map.get(n, n) for n in agent.waiting_for]
        if new_waiting != agent.waiting_for:
            agent.waiting_for = new_waiting


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
