"""Agent killing methods for the ace TUI app."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec

# Re-export for backwards compatibility (_loading.py imports this)
from ._killing_utils import delete_agent_artifacts as delete_agent_artifacts
from ._killing_utils import (
    dismiss_notifications_for_agent,
    dismiss_notifications_for_agents,
    find_workflow_workspace_from_running_field,
)

from ._dismissing import AgentDismissingMixin, persist_dismiss_side_effects

log = logging.getLogger(__name__)
KillKind = Literal["running", "hook", "mentor", "crs", "workflow"]
AgentIdentity = tuple["AgentType", str, str | None]


@dataclass(frozen=True)
class _BulkKillItem:
    agent: Agent
    kind: KillKind
    identities: set[AgentIdentity]


class AgentKillingMixin(AgentDismissingMixin):
    """Mixin providing agent killing methods.

    Inherits dismissal methods from AgentDismissingMixin.
    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    # ChangeSpec state
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: str

    # Agent state
    _agents: list[Agent]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _pinned_agents: set[tuple[AgentType, str, str | None]]
    _agents_with_children: list[Agent]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]]
    _kill_persistence_inflight: set[tuple[AgentType, str, str | None]]

    def _classify_kill_kind(self, agent: Agent) -> KillKind | None:
        """Classify the side effects needed to kill an agent."""
        from ...models.agent import AgentType

        workflow = agent.workflow or ""
        if agent.agent_type == AgentType.WORKFLOW:
            return "workflow"
        if workflow.startswith("axe(fix-hook)") or workflow in (
            "fix-hook",
            "summarize-hook",
        ):
            return "hook"
        if workflow.startswith(("axe(mentor)", "mentor(")) or workflow == "mentor":
            return "mentor"
        if workflow.startswith("axe(crs)") or workflow == "crs":
            return "crs"
        if agent.agent_type == AgentType.RUNNING:
            return "running"
        return None

    def _collect_immediate_kill_identities(self, agent: Agent) -> set[AgentIdentity]:
        """Return identities hidden immediately after killing an agent."""
        from ...models.agent import AgentType

        identities = {agent.identity}
        if agent.agent_type == AgentType.WORKFLOW and not agent.is_workflow_child:
            for step in self._agents_with_children:
                if (
                    step.is_workflow_child
                    and step.parent_timestamp == agent.raw_suffix
                    and step.parent_workflow == agent.workflow
                ):
                    identities.add(step.identity)
        return identities

    def _apply_killed_agents_in_memory(
        self, identities: set[AgentIdentity], *, refresh: bool = True
    ) -> None:
        """Remove killed agents from memory and optionally refresh the Agents tab."""
        if not identities:
            return

        self._dismissed_agents.update(identities)
        for identity in identities:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)

        self._agents = [a for a in self._agents if a.identity not in identities]  # type: ignore[attr-defined]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in identities
        ]
        self._build_panel_indices()  # type: ignore[attr-defined]
        self._clamp_agent_selection_to_active_panel()

        if refresh and self.current_tab == "agents":  # type: ignore[attr-defined]
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True, defer_detail=True
            )

    def _clamp_agent_selection_to_active_panel(self) -> None:
        """Clamp current_idx after an in-memory agent-list mutation."""
        if self._agents:  # type: ignore[attr-defined]
            self.current_idx = min(  # type: ignore[attr-defined]
                self.current_idx,
                len(self._agents) - 1,  # type: ignore[attr-defined]
            )
        else:
            self.current_idx = 0  # type: ignore[attr-defined]

        pinned_indices = getattr(self, "_pinned_panel_indices", [])
        main_indices = getattr(self, "_main_panel_indices", [])
        panel_focus = getattr(self, "_pinned_panel_focused", "main")
        if not pinned_indices and panel_focus == "pinned":
            self._pinned_panel_focused = "main"  # type: ignore[attr-defined]
        elif not main_indices and pinned_indices and panel_focus == "main":
            self._pinned_panel_focused = "pinned"  # type: ignore[attr-defined]

        if hasattr(self, "_active_panel_indices"):
            try:
                active = self._active_panel_indices()  # type: ignore[attr-defined]
            except AttributeError:
                active = main_indices or pinned_indices
        else:
            active = main_indices or pinned_indices
        if self._agents and active and self.current_idx not in active:  # type: ignore[attr-defined]
            if active:
                self.current_idx = active[0]  # type: ignore[attr-defined]

    def _do_kill_agent(self, agent: Agent) -> None:
        """Perform the actual agent kill after confirmation."""
        started = time.perf_counter()
        kind = self._classify_kill_kind(agent)
        if kind is None:
            self.notify(  # type: ignore[attr-defined]
                f"Unknown agent type: {agent.agent_type}", severity="error"
            )
            return

        if agent.pid is not None and not self._kill_process_group(agent.pid):
            return
        self._notify_killed_agent(agent, kind)

        agents_with_children_snapshot = list(self._agents_with_children)
        dismiss_notifications_for_agent(agent)
        self._refresh_notification_count()  # type: ignore[attr-defined]
        self._apply_killed_agents_in_memory(
            self._collect_immediate_kill_identities(agent)
        )

        self.call_later(  # type: ignore[attr-defined]
            self._run_kill_persistence_async,
            agent,
            kind,
            agents_with_children_snapshot,
        )
        log.debug(
            "agent kill immediate stage: kind=%s identity=%s elapsed=%.3fs",
            kind,
            agent.identity,
            time.perf_counter() - started,
        )

    def _do_bulk_kill_agents(
        self, killable: list[Agent], dismissable: list[Agent] | None = None
    ) -> None:
        """Kill/dismiss marked agents as one optimistic UI transaction."""
        started = time.perf_counter()
        dismissable = dismissable or []
        agents_with_children_snapshot = list(self._agents_with_children)
        live_ids = {a.identity for a in agents_with_children_snapshot}
        seen_ids: set[AgentIdentity] = set()
        kill_items: list[_BulkKillItem] = []
        failed_ids: set[AgentIdentity] = set()

        for agent in killable:
            if agent.identity not in live_ids or agent.identity in seen_ids:
                continue
            kind = self._classify_kill_kind(agent)
            if kind is None:
                self.notify(  # type: ignore[attr-defined]
                    f"Unknown agent type: {agent.agent_type}", severity="error"
                )
                failed_ids.add(agent.identity)
                continue
            if agent.pid is not None and not self._kill_process_group(agent.pid):
                failed_ids.add(agent.identity)
                continue
            identities = self._collect_immediate_kill_identities(agent)
            seen_ids.update(identities)
            kill_items.append(
                _BulkKillItem(agent=agent, kind=kind, identities=identities)
            )

        dismiss_candidates = [
            a
            for a in dismissable
            if a.identity in live_ids
            and a.identity not in seen_ids
            and a.identity not in failed_ids
        ]
        dismissed_ids = self._collect_dismissal_identities(dismiss_candidates)
        killed_ids: set[AgentIdentity] = set()
        for item in kill_items:
            killed_ids.update(item.identities)

        for identity in dismissed_ids:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)
        self._dismissed_agents.update(dismissed_ids)
        self._append_dismissed_agent_objects(dismiss_candidates, dismissed_ids)

        removed_ids = killed_ids | dismissed_ids
        self._marked_agents.clear()  # type: ignore[attr-defined]
        self._apply_killed_agents_in_memory(removed_ids, refresh=False)
        self._refresh_notification_count()  # type: ignore[attr-defined]
        if self.current_tab == "agents":  # type: ignore[attr-defined]
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True, defer_detail=True
            )

        killed_count = len(kill_items)
        dismissed_count = len(dismiss_candidates)
        if killed_count:
            s = "s" if killed_count != 1 else ""
            self.notify(f"Killed {killed_count} agent{s}")  # type: ignore[attr-defined]
        if dismissed_count:
            s = "s" if dismissed_count != 1 else ""
            self.notify(f"Dismissed {dismissed_count} agent{s}")  # type: ignore[attr-defined]

        if kill_items or dismiss_candidates:
            self.call_later(  # type: ignore[attr-defined]
                self._run_bulk_kill_persistence_async,
                kill_items,
                dismiss_candidates,
                set(self._dismissed_agents),
                agents_with_children_snapshot,
            )
        log.debug(
            "bulk agent kill immediate stage: killed=%d dismissed=%d elapsed=%.3fs",
            killed_count,
            dismissed_count,
            time.perf_counter() - started,
        )

    async def _run_bulk_kill_persistence_async(
        self,
        kill_items: list[_BulkKillItem],
        dismissable: list[Agent],
        dismissed_snapshot: set[AgentIdentity],
        agents_with_children_snapshot: list[Agent],
    ) -> None:
        """Persist bulk kill/dismiss side effects in a worker thread."""
        inflight = {item.agent.identity for item in kill_items}
        if inflight & self._kill_persistence_inflight:
            return
        self._kill_persistence_inflight.update(inflight)

        started = time.perf_counter()
        try:
            await asyncio.to_thread(
                persist_bulk_kill_side_effects,
                kill_items,
                dismissable,
                dismissed_snapshot,
                agents_with_children_snapshot,
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Bulk kill cleanup failed: {exc}",
                severity="error",
            )
        finally:
            self._kill_persistence_inflight.difference_update(inflight)
            log.debug(
                "bulk agent kill persistence: killed=%d dismissed=%d elapsed=%.3fs",
                len(kill_items),
                len(dismissable),
                time.perf_counter() - started,
            )
            self._schedule_agents_async_refresh()  # type: ignore[attr-defined]

    def _notify_killed_agent(self, agent: Agent, kind: KillKind) -> None:
        """Emit kill notification message for an already-signaled process."""
        if agent.pid is None:
            return
        if kind == "workflow":
            self.notify(f"Killed workflow (PID {agent.pid})")  # type: ignore[attr-defined]
            return
        if kind == "hook":
            self.notify(f"Killed hook agent (PID {agent.pid})")  # type: ignore[attr-defined]
            return
        if kind == "mentor":
            self.notify(f"Killed mentor agent (PID {agent.pid})")  # type: ignore[attr-defined]
            return
        if kind == "crs":
            self.notify(f"Killed CRS agent (PID {agent.pid})")  # type: ignore[attr-defined]
            return
        self.notify(f"Killed agent (PID {agent.pid})")  # type: ignore[attr-defined]

    async def _run_kill_persistence_async(
        self,
        agent: Agent,
        kind: KillKind,
        agents_with_children_snapshot: list[Agent] | None = None,
    ) -> None:
        """Persist kill side effects in a worker thread."""
        identity = agent.identity
        if identity in self._kill_persistence_inflight:
            return
        self._kill_persistence_inflight.add(identity)

        started = time.perf_counter()
        if agents_with_children_snapshot is None:
            agents_with_children_snapshot = list(self._agents_with_children)

        try:
            await asyncio.to_thread(
                persist_kill_side_effects,
                agent,
                kind,
                agents_with_children_snapshot,
            )
            # Persist the latest dismissed set snapshot after worker-side writes.
            from ....dismissed_agents import save_dismissed_agents

            await asyncio.to_thread(save_dismissed_agents, set(self._dismissed_agents))
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                f"Kill cleanup failed for {agent.display_name}: {exc}",
                severity="error",
            )
        finally:
            self._kill_persistence_inflight.discard(identity)
            log.debug(
                "agent kill persistence: kind=%s identity=%s elapsed=%.3fs",
                kind,
                identity,
                time.perf_counter() - started,
            )
            self._schedule_agents_async_refresh()  # type: ignore[attr-defined]

    def _kill_process_group(self, pid: int) -> bool:
        """Kill a process group by PID.

        Args:
            pid: Process ID to kill.

        Returns:
            True if kill succeeded or process was already dead, False on error.
        """
        try:
            os.killpg(pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            # Process already dead - still consider success
            return True
        except PermissionError:
            self.notify(  # type: ignore[attr-defined]
                f"Permission denied killing PID {pid}", severity="error"
            )
            return False

    def _kill_running_agent(self, agent: Agent) -> None:
        """Kill a RUNNING type agent (workspace-based)."""
        from sase.running_field import release_workspace

        if agent.pid is None:
            return

        if not self._kill_process_group(agent.pid):
            return

        self.notify(f"Killed agent (PID {agent.pid})")  # type: ignore[attr-defined]

        # Release the workspace claim
        if agent.workspace_num is not None:
            release_workspace(
                agent.project_file,
                agent.workspace_num,
                agent.workflow,
                agent.cl_name,
            )

    def _kill_hook_agent(self, agent: Agent) -> None:
        """Kill a hook agent (fix-hook or summarize-hook)."""
        from ....changespec import parse_project_file
        from ....hooks import update_changespec_hooks_field
        from ....hooks.processes import mark_hook_agents_as_killed

        if agent.pid is None:
            return

        if not self._kill_process_group(agent.pid):
            return

        self.notify(f"Killed hook agent (PID {agent.pid})")  # type: ignore[attr-defined]

        # Update hook status to killed_agent
        changespecs = parse_project_file(agent.project_file)
        for cs in changespecs:
            if cs.name == agent.cl_name and cs.hooks:
                killed_hook_agents = []
                for hook in cs.hooks:
                    if hook.status_lines:
                        for sl in hook.status_lines:
                            if (
                                sl.suffix_type == "running_agent"
                                and sl.suffix == agent.raw_suffix
                            ):
                                killed_hook_agents.append((hook, sl, agent.pid))

                if killed_hook_agents:
                    updated_hooks = mark_hook_agents_as_killed(
                        cs.hooks, killed_hook_agents
                    )
                    update_changespec_hooks_field(
                        agent.project_file, agent.cl_name, updated_hooks
                    )
                break

    def _kill_mentor_agent(self, agent: Agent) -> None:
        """Kill a mentor agent."""
        from ....changespec import parse_project_file
        from ....hooks.processes import mark_mentor_agents_as_killed
        from ....mentors import update_changespec_mentors_field

        if agent.pid is None:
            return

        if not self._kill_process_group(agent.pid):
            return

        self.notify(f"Killed mentor agent (PID {agent.pid})")  # type: ignore[attr-defined]

        # Update mentor status to killed_agent
        changespecs = parse_project_file(agent.project_file)
        for cs in changespecs:
            if cs.name == agent.cl_name and cs.mentors:
                killed_mentor_agents = []
                for entry in cs.mentors:
                    if entry.status_lines:
                        for sl in entry.status_lines:
                            if (
                                sl.suffix_type == "running_agent"
                                and sl.suffix == agent.raw_suffix
                            ):
                                killed_mentor_agents.append((entry, sl, agent.pid))

                if killed_mentor_agents:
                    updated_mentors = mark_mentor_agents_as_killed(
                        cs.mentors, killed_mentor_agents
                    )
                    update_changespec_mentors_field(
                        agent.project_file, agent.cl_name, updated_mentors
                    )
                break

    def _kill_crs_agent(self, agent: Agent) -> None:
        """Kill a CRS (comments) agent."""
        from ....changespec import parse_project_file
        from ....comments import update_changespec_comments_field
        from ....comments.operations import mark_comment_agents_as_killed

        if agent.pid is None:
            return

        if not self._kill_process_group(agent.pid):
            return

        self.notify(f"Killed CRS agent (PID {agent.pid})")  # type: ignore[attr-defined]

        # Update comment status to killed_agent
        changespecs = parse_project_file(agent.project_file)
        for cs in changespecs:
            if cs.name == agent.cl_name and cs.comments:
                killed_comment_agents = []
                for comment in cs.comments:
                    if (
                        comment.suffix_type == "running_agent"
                        and comment.suffix == agent.raw_suffix
                    ):
                        killed_comment_agents.append((comment, agent.pid))

                if killed_comment_agents:
                    updated_comments = mark_comment_agents_as_killed(
                        cs.comments, killed_comment_agents
                    )
                    update_changespec_comments_field(
                        agent.project_file, agent.cl_name, updated_comments
                    )
                break

    def _kill_workflow_agent(self, agent: Agent) -> None:
        """Kill a workflow agent.

        Args:
            agent: The workflow agent to kill.
        """
        from sase.running_field import release_workspace

        # Kill the workflow process if it has a PID
        if agent.pid is not None:
            if not self._kill_process_group(agent.pid):
                return
            self.notify(f"Killed workflow (PID {agent.pid})")  # type: ignore[attr-defined]

        # Determine workflow name (steps use parent_workflow)
        workflow_name = agent.workflow
        if agent.is_workflow_child and agent.parent_workflow:
            workflow_name = agent.parent_workflow

        # Release the workspace claim (workflow claims use "workflow(name)" format)
        if workflow_name is not None:
            # Try agent's workspace_num first, then look it up from RUNNING field
            workspace_num = agent.workspace_num
            if workspace_num is None:
                # For steps, don't use the decorated cl_name for lookup
                # Also treat "unknown" as None since it's a placeholder
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

        # Save bundle before deleting artifacts (for revive support)
        self._save_agent_bundle(agent)

        # Delete artifact files so the agent won't be reloaded on restart
        delete_agent_artifacts(agent.artifacts_dir or agent.get_artifacts_dir())

        # Track dismissal as safety net (ensures agent is filtered even if
        # workspace release failed or RUNNING field persists)
        self._persist_dismissed_agent(agent.identity)

        # Also dismiss child steps (use unfiltered list so children are
        # found even when the workflow fold is collapsed).
        if not agent.is_workflow_child:
            for step in self._agents_with_children:
                if (
                    step.is_workflow_child
                    and step.parent_timestamp == agent.raw_suffix
                    and step.parent_workflow == agent.workflow
                ):
                    self._dismissed_agents.add(step.identity)
            # Persist after batching all child dismissals
            from ....dismissed_agents import save_dismissed_agents

            save_dismissed_agents(self._dismissed_agents)

    def _kill_and_dismiss_all_agents(self) -> None:
        """Kill all running agents and dismiss all done agents (double-confirm)."""
        from ._core import DISMISSABLE_STATUSES

        killable = [
            a
            for a in self._agents
            if a.pid is not None
            and a.status not in DISMISSABLE_STATUSES
            and a.identity not in self._pinned_agents
        ]
        dismissable = [
            a
            for a in self._agents
            if a.status in DISMISSABLE_STATUSES
            and a.raw_suffix is not None
            and a.identity not in self._pinned_agents
        ]

        if not killable and not dismissable:
            self.notify("No agents to kill or dismiss", severity="warning")  # type: ignore[attr-defined]
            return

        # Build description showing both groups
        desc_parts: list[str] = []
        if killable:
            k_count = len(killable)
            k_s = "s" if k_count != 1 else ""
            desc_parts.append(f"Kill: {k_count} running agent{k_s}")
            for agent in killable:
                name = agent.display_name
                suffix = f" @{agent.agent_name}" if agent.agent_name else ""
                desc_parts.append(f"  {name}{suffix}")
        if dismissable:
            d_count = len(dismissable)
            d_s = "s" if d_count != 1 else ""
            desc_parts.append(f"Dismiss: {d_count} completed agent{d_s}")
            for agent in dismissable:
                name = agent.display_name
                suffix = f" @{agent.agent_name}" if agent.agent_name else ""
                desc_parts.append(f"  {name}{suffix}")
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmKillAllModal

        def on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                # Kill running agents first
                for agent in killable:
                    self._do_kill_agent(agent)
                # Then dismiss completed agents
                if dismissable:
                    self._do_dismiss_all(dismissable)

        self.push_screen(ConfirmKillAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]


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
    kill_items: list[_BulkKillItem],
    dismissable: list[Agent],
    dismissed_snapshot: set[AgentIdentity],
    agents_with_children_snapshot: list[Agent],
) -> None:
    """Apply filesystem/project-file side effects for a bulk kill operation."""
    from ....dismissed_agents import save_dismissed_agents

    for item in kill_items:
        persist_kill_side_effects(
            item.agent,
            item.kind,
            agents_with_children_snapshot,
        )
    for agent in dismissable:
        persist_dismiss_side_effects(agent, agents_with_children_snapshot)

    if kill_items or dismissable:
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

    changespecs = parse_project_file(agent.project_file)
    for cs in changespecs:
        if cs.name == agent.cl_name and cs.hooks:
            killed_hook_agents = []
            for hook in cs.hooks:
                if hook.status_lines:
                    for sl in hook.status_lines:
                        if (
                            sl.suffix_type == "running_agent"
                            and sl.suffix == agent.raw_suffix
                        ):
                            killed_hook_agents.append((hook, sl, agent.pid))

            if killed_hook_agents:
                updated_hooks = mark_hook_agents_as_killed(cs.hooks, killed_hook_agents)
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

    changespecs = parse_project_file(agent.project_file)
    for cs in changespecs:
        if cs.name == agent.cl_name and cs.mentors:
            killed_mentor_agents = []
            for entry in cs.mentors:
                if entry.status_lines:
                    for sl in entry.status_lines:
                        if (
                            sl.suffix_type == "running_agent"
                            and sl.suffix == agent.raw_suffix
                        ):
                            killed_mentor_agents.append((entry, sl, agent.pid))

            if killed_mentor_agents:
                updated_mentors = mark_mentor_agents_as_killed(
                    cs.mentors, killed_mentor_agents
                )
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

    changespecs = parse_project_file(agent.project_file)
    for cs in changespecs:
        if cs.name == agent.cl_name and cs.comments:
            killed_comment_agents = []
            for comment in cs.comments:
                if (
                    comment.suffix_type == "running_agent"
                    and comment.suffix == agent.raw_suffix
                ):
                    killed_comment_agents.append((comment, agent.pid))

            if killed_comment_agents:
                updated_comments = mark_comment_agents_as_killed(
                    cs.comments, killed_comment_agents
                )
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

    # Also remove child artifacts for workflow parents.
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
