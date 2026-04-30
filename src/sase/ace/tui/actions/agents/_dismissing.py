"""Agent dismissal methods for the ace TUI app."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from sase.core.agent_cleanup_wire import AgentCleanupPlanWire

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


def _agent_wire_identity(agent: Agent) -> tuple[str, str, str | None]:
    return (agent.agent_type.value, agent.cl_name, agent.raw_suffix)


def _wire_identity_key(identity: Any) -> tuple[str, str, str | None]:
    return (
        str(identity.agent_type),
        str(identity.cl_name),
        identity.raw_suffix,
    )


def _agent_identity_from_wire(identity: Any) -> AgentIdentity:
    from ...models.agent import AgentType

    return (
        AgentType(str(identity.agent_type)),
        str(identity.cl_name),
        identity.raw_suffix,
    )


def _plan_dismissal_side_effects(
    agents: list[Agent],
    agents_with_children_snapshot: list[Agent],
    *,
    taken_dismissed_names: set[str] | None = None,
) -> AgentCleanupPlanWire:
    """Return a Rust/Python cleanup plan for dismissal side effects."""
    from sase.core.agent_cleanup_facade import (
        agents_to_cleanup_targets,
        plan_agent_cleanup,
    )
    from sase.core.agent_cleanup_wire import (
        AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        CLEANUP_MODE_DISMISS_COMPLETED,
        CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        AgentCleanupIdentityWire,
        AgentCleanupRequestWire,
    )

    identities = tuple(
        AgentCleanupIdentityWire(
            agent_type=agent.agent_type.value,
            cl_name=agent.cl_name,
            raw_suffix=agent.raw_suffix,
        )
        for agent in agents
    )
    request = AgentCleanupRequestWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        mode=CLEANUP_MODE_DISMISS_COMPLETED,
        identities=identities,
        taken_dismissed_names=tuple(sorted(taken_dismissed_names or ())),
    )
    return plan_agent_cleanup(
        agents_to_cleanup_targets(agents_with_children_snapshot),
        request,
    )


def apply_dismissal_rename_intents(
    agents_with_children_snapshot: list[Agent],
    plan: object,
) -> dict[str, str]:
    """Mutate agent names according to cleanup rename intents."""
    by_identity = {
        _agent_wire_identity(agent): agent for agent in agents_with_children_snapshot
    }
    name_map: dict[str, str] = {}
    side_effects = getattr(plan, "side_effects", None)
    for intent in getattr(side_effects, "dismissal_rename_allocations", ()):
        agent = by_identity.get(_wire_identity_key(intent.identity))
        if agent is None:
            continue
        old_name = agent.agent_name
        agent.agent_name = intent.new_name
        if old_name and old_name != intent.new_name:
            name_map[old_name] = intent.new_name
    if not name_map:
        return dict(getattr(side_effects, "wait_reference_rewrite_map", ()) or ())
    return name_map


def dismissed_identities_from_plan(plan: object) -> set[AgentIdentity]:
    side_effects = getattr(plan, "side_effects", None)
    identities = {
        _agent_identity_from_wire(identity)
        for identity in getattr(side_effects, "dismissed_index_additions", ())
    }
    return identities


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
        self._dismiss_done_agents_from(
            self._agents_in_focused_panel(),  # type: ignore[attr-defined]
            empty_message="No agents to dismiss",
        )

    def _dismiss_all_done_agents_global(self) -> None:
        """Dismiss all done/failed agents across all loaded panels."""
        self._dismiss_done_agents_from(
            list(self._agents),
            empty_message="No agents to dismiss",
        )

    def _dismiss_done_agents_from(
        self, agents: list[Agent], *, empty_message: str
    ) -> None:
        """Dismiss all done/failed agents from a candidate list."""
        from ._core import DISMISSABLE_STATUSES

        dismissable = [
            a
            for a in agents
            if a.status in DISMISSABLE_STATUSES and a.raw_suffix is not None
        ]

        if not dismissable:
            self.notify(empty_message, severity="warning")  # type: ignore[attr-defined]
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
        if not agents:
            return

        agents_with_children_snapshot = list(self._agents_with_children)

        from sase.agent.names import collect_dismissed_taken_names

        allocated_names: set[str] = collect_dismissed_taken_names()
        cleanup_plan = _plan_dismissal_side_effects(
            agents,
            agents_with_children_snapshot,
            taken_dismissed_names=allocated_names,
        )
        name_map = apply_dismissal_rename_intents(
            agents_with_children_snapshot,
            cleanup_plan,
        )
        dismissed_identities = dismissed_identities_from_plan(cleanup_plan)

        for identity in dismissed_identities:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)
        self._dismissed_agents.update(dismissed_identities)

        count = len(agents)
        s = "s" if count != 1 else ""
        self.notify(f"Dismissed {count} agent{s}")  # type: ignore[attr-defined]
        self._apply_dismissal_in_memory(agents)
        apply_in_memory_reference_rewrites(self._agents_with_children, name_map)
        self._refresh_notification_count()  # type: ignore[attr-defined]

        self.call_later(  # type: ignore[attr-defined]
            self._run_bulk_dismiss_persistence_async,
            list(agents),
            set(self._dismissed_agents),
            agents_with_children_snapshot,
            cleanup_plan,
            name_map,
        )

    async def _run_bulk_dismiss_persistence_async(
        self,
        agents: list[Agent],
        dismissed_snapshot: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
        cleanup_plan: object | None = None,
        name_map: dict[str, str] | None = None,
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
                name_map or {},
                cleanup_plan,
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
        cleanup_plan = _plan_dismissal_side_effects(
            [agent],
            agents_with_children_snapshot,
        )
        name_map = apply_dismissal_rename_intents(
            agents_with_children_snapshot,
            cleanup_plan,
        )
        identities = dismissed_identities_from_plan(cleanup_plan)
        if not identities:
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
        apply_in_memory_reference_rewrites(self._agents_with_children, name_map)
        self.call_later(  # type: ignore[attr-defined]
            self._run_dismiss_persistence_async,
            agent,
            set(self._dismissed_agents),
            agents_with_children_snapshot,
            cleanup_plan,
            name_map,
        )

    async def _run_dismiss_persistence_async(
        self,
        agent: Agent,
        dismissed_snapshot: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
        cleanup_plan: object | None = None,
        name_map: dict[str, str] | None = None,
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
                name_map or {},
                cleanup_plan,
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
    cleanup_plan: object | None = None,
) -> None:
    """Persist all side effects for one optimistic dismiss operation."""
    from ....dismissed_agents import save_dismissed_agents
    from sase.agent.dismissed_name_rewrites import rewrite_dismissed_references

    rewrite_dismissed_references(name_map)
    if not persist_cleanup_side_effect_intents(
        cleanup_plan,
        agents_with_children_snapshot,
    ):
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
    cleanup_plan: object | None = None,
) -> None:
    """Persist all side effects for an optimistic batch dismiss operation."""
    from ....dismissed_agents import save_dismissed_agents
    from sase.agent.dismissed_name_rewrites import rewrite_dismissed_references

    rewrite_dismissed_references(name_map)
    if not persist_cleanup_side_effect_intents(
        cleanup_plan,
        agents_with_children_snapshot,
    ):
        related: list[Agent] = []
        for agent in agents:
            persist_dismiss_side_effects(agent, agents_with_children_snapshot)
            related.extend(
                _agents_related_to_dismissal(agent, agents_with_children_snapshot)
            )
        if related:
            dismiss_notifications_for_agents(related)
    save_dismissed_agents(dismissed_snapshot)


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
        _agent_wire_identity(agent): agent for agent in agents_with_children_snapshot
    }

    for intent in getattr(side_effects, "bundle_save_candidates", ()):
        agent = by_identity.get(_wire_identity_key(intent.identity))
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
        agent = by_identity.get(_wire_identity_key(intent.identity))
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

    notification_agents = [
        agent
        for agent in agents_with_children_snapshot
        if _agent_wire_identity(agent)
        in {
            _wire_identity_key(intent.identity)
            for intent in getattr(side_effects, "notification_dismiss_candidates", ())
        }
    ]
    if notification_agents:
        dismiss_notifications_for_agents(notification_agents)
    return True


def apply_in_memory_reference_rewrites(
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
