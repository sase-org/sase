"""Agent killing methods for the ace TUI app."""

from __future__ import annotations

import asyncio
import logging
import os  # noqa: F401  # kept so tests can patch `_killing.os.killpg`
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec

# Re-export for backwards compatibility (_loading.py imports this, tests patch it)
from ._killing_utils import delete_agent_artifacts as delete_agent_artifacts
from ._killing_utils import (
    dismiss_notifications_for_agents,
)

from ._dismissing import AgentDismissingMixin
from ._kill_persistence import (
    AgentIdentity,
    BulkKillItem,
    KillKind,
    persist_bulk_kill_side_effects,
    persist_kill_side_effects,
)
from ._kill_type_handlers import AgentKillTypeHandlersMixin

log = logging.getLogger(__name__)


class AgentKillingMixin(AgentKillTypeHandlersMixin, AgentDismissingMixin):
    """Mixin providing agent killing methods.

    Inherits per-type kill methods from AgentKillTypeHandlersMixin and
    dismissal methods from AgentDismissingMixin.
    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    # ChangeSpec state
    changespecs: list[ChangeSpec]
    current_idx: int
    current_tab: str

    # Agent state
    _agents: list[Agent]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
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

    def _agents_related_to_kill(
        self, agent: Agent, agents_with_children_snapshot: list[Agent]
    ) -> list[Agent]:
        """Return agents whose notifications should be dismissed when killing ``agent``.

        Includes the agent itself plus any workflow-child rows when killing a
        workflow parent (mirroring :meth:`_collect_immediate_kill_identities`
        but returning Agent objects so they can be passed to
        ``dismiss_notifications_for_agents``).
        """
        from ...models.agent import AgentType

        related: list[Agent] = [agent]
        if agent.agent_type == AgentType.WORKFLOW and not agent.is_workflow_child:
            for step in agents_with_children_snapshot:
                if (
                    step.is_workflow_child
                    and step.parent_timestamp == agent.raw_suffix
                    and step.parent_workflow == agent.workflow
                ):
                    related.append(step)
        return related

    def _apply_killed_agents_in_memory(
        self, identities: set[AgentIdentity], *, refresh: bool = True
    ) -> None:
        """Remove killed agents from memory and optionally refresh the Agents tab."""
        if not identities:
            return

        # Capture the pre-mutation visible-row anchor so the post-mutation
        # focus lands on the agent visually below the killed one.
        prior_pos = self._capture_focused_visible_pos()  # type: ignore[attr-defined]

        self._dismissed_agents.update(identities)
        for identity in identities:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)

        self._agents = [a for a in self._agents if a.identity not in identities]  # type: ignore[attr-defined]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in identities
        ]
        self._restore_focus_after_removal(prior_pos)  # type: ignore[attr-defined]

        if refresh and self.current_tab == "agents":  # type: ignore[attr-defined]
            self._refresh_agents_display(  # type: ignore[attr-defined]
                list_changed=True, defer_detail=True
            )

    def _clamp_agent_selection(self) -> None:
        """Clamp current_idx after an in-memory agent-list mutation.

        Thin wrapper for callers (revive, hide-toggle) that have no
        pre-mutation visible-row anchor — delegates to
        :meth:`_restore_focus_after_removal` with ``None`` so the unified
        clamp fallback lives in one place.
        """
        self._restore_focus_after_removal(None)  # type: ignore[attr-defined]

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
        # Snapshot the dismissed set BEFORE the optimistic mutation so re-entrant
        # kills cannot corrupt the set the persistence worker writes back.
        dismissed_snapshot = set(self._dismissed_agents)
        dismissed_snapshot.update(self._collect_immediate_kill_identities(agent))
        self._apply_killed_agents_in_memory(
            self._collect_immediate_kill_identities(agent)
        )

        self.call_later(  # type: ignore[attr-defined]
            self._run_kill_persistence_async,
            agent,
            kind,
            agents_with_children_snapshot,
            dismissed_snapshot,
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
        kill_items: list[BulkKillItem] = []
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
                BulkKillItem(agent=agent, kind=kind, identities=identities)
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
        kill_items: list[BulkKillItem],
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
        success = True
        try:
            await asyncio.to_thread(
                persist_bulk_kill_side_effects,
                kill_items,
                dismissable,
                dismissed_snapshot,
                agents_with_children_snapshot,
            )
        except Exception as exc:
            success = False
            self.notify(  # type: ignore[attr-defined]
                f"Bulk kill cleanup failed: {exc}",
                severity="error",
            )
            self._schedule_agents_async_refresh()  # type: ignore[attr-defined]
        finally:
            self._kill_persistence_inflight.difference_update(inflight)
            log.debug(
                "bulk agent kill persistence: killed=%d dismissed=%d elapsed=%.3fs",
                len(kill_items),
                len(dismissable),
                time.perf_counter() - started,
            )
            if success:
                await self._refresh_notification_count_async()  # type: ignore[attr-defined]

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
        dismissed_snapshot: set[AgentIdentity] | None = None,
    ) -> None:
        """Persist kill side effects in a worker thread."""
        identity = agent.identity
        if identity in self._kill_persistence_inflight:
            return
        self._kill_persistence_inflight.add(identity)

        started = time.perf_counter()
        if agents_with_children_snapshot is None:
            agents_with_children_snapshot = list(self._agents_with_children)
        if dismissed_snapshot is None:
            dismissed_snapshot = set(self._dismissed_agents)

        success = True
        try:
            await asyncio.to_thread(
                persist_kill_side_effects,
                agent,
                kind,
                agents_with_children_snapshot,
            )
            # Persist the dismissed-set snapshot captured on the UI thread,
            # then rewrite the notifications file (single read+write) for
            # this agent and any workflow-child rows hidden alongside it.
            from ....dismissed_agents import save_dismissed_agents

            await asyncio.to_thread(save_dismissed_agents, dismissed_snapshot)
            related = self._agents_related_to_kill(agent, agents_with_children_snapshot)
            await asyncio.to_thread(dismiss_notifications_for_agents, related)
        except Exception as exc:
            success = False
            self.notify(  # type: ignore[attr-defined]
                f"Kill cleanup failed for {agent.display_name}: {exc}",
                severity="error",
            )
            self._schedule_agents_async_refresh()  # type: ignore[attr-defined]
        finally:
            self._kill_persistence_inflight.discard(identity)
            log.debug(
                "agent kill persistence: kind=%s identity=%s elapsed=%.3fs",
                kind,
                identity,
                time.perf_counter() - started,
            )
            if success:
                await self._refresh_notification_count_async()  # type: ignore[attr-defined]

    def _kill_and_dismiss_all_agents(self) -> None:
        """Kill all running agents and dismiss all done agents (double-confirm)."""
        from ._core import DISMISSABLE_STATUSES

        panel_agents = self._agents_in_focused_panel()  # type: ignore[attr-defined]
        killable = [
            a
            for a in panel_agents
            if a.pid is not None and a.status not in DISMISSABLE_STATUSES
        ]
        dismissable = [
            a
            for a in panel_agents
            if a.status in DISMISSABLE_STATUSES and a.raw_suffix is not None
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
                    self._do_dismiss_all(dismissable)  # type: ignore[attr-defined]

        self.push_screen(ConfirmKillAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]
