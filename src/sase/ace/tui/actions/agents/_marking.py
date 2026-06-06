"""Agent marking actions for the ace TUI app."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Literal

from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
)

from ._dismiss_cleanup import AgentIdentity
from ._recent_dismissal_groups import cache_recent_dismissed_agent_group
from ._saved_group_records import (
    build_saved_agent_group,
    normalize_saved_group_name,
    plural_agent,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from sase.core.agent_group_archive_wire import SavedAgentGroupWire

TabName = Literal["changespecs", "agents", "axe"]
log = logging.getLogger(__name__)


def _persist_marked_agent_group_save(
    agents: list[Agent],
    dismissed_snapshot: set[AgentIdentity],
    added: set[AgentIdentity],
    group: SavedAgentGroupWire,
    group_name: str | None = None,
) -> None:
    """Persist non-killing marked-agent dismissal side effects."""
    del group_name

    from ....dismissed_agents import (
        record_recent_dismissed_agent_group,
        save_dismissed_agent_group,
        save_dismissed_agents,
        save_dismissed_bundle,
    )

    for agent in agents:
        if not agent._from_changespec:
            save_dismissed_bundle(agent)

    save_dismissed_agent_group(group)
    record_recent_dismissed_agent_group(group)

    if save_dismissed_agents(dismissed_snapshot):
        try:
            sync_dismissed_agent_artifact_index(dismissed_snapshot, added=added)
        except Exception:
            pass


class AgentMarkingMixin:
    """Mixin providing agent marking actions for the Agents tab.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _recent_dismissed_agent_groups: list[SavedAgentGroupWire]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]]
    _current_group_key: tuple[str, ...] | None

    def _toggle_mark_agent(self) -> None:
        """Toggle the mark on the currently-selected agent."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        identity = agent.identity
        if identity in self._marked_agents:
            self._marked_agents.discard(identity)
        else:
            self._marked_agents.add(identity)

        # Auto-advance cursor to the next visible agent row (wraparound).
        prev_idx = self.current_idx
        self._advance_mark_selection(prev_idx)

        # Patch the just-marked row in place; the cursor's new position
        # is reflected by the per-panel highlight update so we avoid
        # rebuilding the whole tree for a one-bit mark change.
        patched = self._try_patch_agent_row(agent)  # type: ignore[attr-defined]
        if patched and prev_idx != self.current_idx:
            # Selection moved off prev_idx and onto current_idx — update
            # the on-screen highlight without a rebuild.
            self._refresh_panel_highlights()  # type: ignore[attr-defined]
            # Also patch the now-selected agent so its name styling
            # reflects the new selection state.
            new_agent = self._agents[self.current_idx]
            self._try_patch_agent_row(new_agent)  # type: ignore[attr-defined]
        if not patched:
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

    def _advance_mark_selection(self, prev_idx: int) -> None:
        """Move mark focus to the next visible agent row.

        Marking targets agents, not collapsed banner rows, so auto-advance
        walks ``_agents_visible_order()`` rather than the full selectable
        stop list. When visible-order helpers are unavailable or the
        current agent is hidden, fall back to the legacy raw-list step.
        """
        if len(self._agents) <= 1:
            return

        try:
            visible = self._agents_visible_order()  # type: ignore[attr-defined]
        except Exception:
            visible = []

        if visible:
            try:
                pos = visible.index(prev_idx)
            except ValueError:
                pass
            else:
                self.current_idx = visible[(pos + 1) % len(visible)]
                self._current_group_key = None
                return

        self.current_idx = (prev_idx + 1) % len(self._agents)
        self._current_group_key = None

    def _clear_agent_marks(self) -> None:
        """Clear every agent mark."""
        if not self._marked_agents:
            self.notify("No marks to clear", severity="warning")  # type: ignore[attr-defined]
            return

        count = len(self._marked_agents)
        self._marked_agents = set()
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        self.notify(f"Cleared {count} mark(s)")  # type: ignore[attr-defined]

    def _prune_stale_marked_agents(self) -> None:
        """Drop marked identities that no longer appear in the agent list."""
        if not self._marked_agents:
            return
        live_identities = {a.identity for a in self._agents}
        live_identities.update(a.identity for a in self._agents_with_children)
        stale = self._marked_agents - live_identities
        if stale:
            self._marked_agents -= stale

    def _bulk_kill_marked_agents(self) -> None:
        """Kill / dismiss every marked agent after a single confirmation."""
        if not self._marked_agents:
            return

        marked_agents: list[Agent] = [
            a for a in self._agents_with_children if a.identity in self._marked_agents
        ]
        if not marked_agents:
            self._marked_agents = set()
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        self._present_bulk_kill_modal(marked_agents)

    def _present_bulk_kill_modal(
        self, agents: list[Agent], *, header: str | None = None
    ) -> None:
        """Show the kill/dismiss confirmation modal for an arbitrary agent set.

        Partitions *agents* into killable (live PID + non-dismissable
        status) and dismissable buckets, builds the per-agent description,
        and pushes the matching ``ConfirmKillAllModal`` /
        ``ConfirmDismissAllModal``.  On confirm, routes through the same
        ``_do_bulk_kill_agents`` machinery used by the marked-set path.
        """
        from ._core import DISMISSABLE_STATUSES

        killable: list[Agent] = [
            a
            for a in agents
            if a.pid is not None and a.status not in DISMISSABLE_STATUSES
        ]
        dismissable: list[Agent] = [
            a for a in agents if a.status in DISMISSABLE_STATUSES or a.pid is None
        ]

        desc_parts: list[str] = []
        if header:
            desc_parts.append(header)
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
            desc_parts.append(f"Dismiss: {d_count} agent{d_s}")
            for agent in dismissable:
                name = agent.display_name
                suffix = f" @{agent.agent_name}" if agent.agent_name else ""
                desc_parts.append(f"  {name}{suffix}")
        agent_description = "\n".join(desc_parts)

        from ...modals import ConfirmDismissAllModal, ConfirmKillAllModal

        def on_dismiss(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._do_bulk_kill_agents(killable, dismissable)  # type: ignore[attr-defined]

        if killable:
            self.push_screen(ConfirmKillAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]
        else:
            self.push_screen(ConfirmDismissAllModal(agent_description), on_dismiss)  # type: ignore[attr-defined]

    def _marked_agent_group_candidates(self) -> list[Agent]:
        """Return marked agents plus workflow children cascaded from parents."""
        if not self._marked_agents:
            return []

        marked = set(self._marked_agents)
        parent_keys = {
            (agent.raw_suffix, agent.workflow)
            for agent in self._agents_with_children
            if agent.identity in marked
            and not agent.is_workflow_child
            and agent.raw_suffix is not None
        }
        candidates: list[Agent] = []
        seen: set[AgentIdentity] = set()
        for agent in self._agents_with_children:
            include = agent.identity in marked
            if not include and agent.is_workflow_child:
                include = (agent.parent_timestamp, agent.parent_workflow) in parent_keys
            if not include or agent.identity in seen:
                continue
            candidates.append(agent)
            seen.add(agent.identity)
        return candidates

    def _prompt_and_save_marked_agent_group(self) -> None:
        """Prompt for an optional group name before saving marked agents."""
        if not self._marked_agents:
            self.notify("No agents marked", severity="warning")  # type: ignore[attr-defined]
            return

        agents = self._marked_agent_group_candidates()
        if not agents:
            self._marked_agents = set()
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        from ...modals import SaveAgentGroupModal, SaveAgentGroupResult

        def on_dismiss(result: SaveAgentGroupResult | None) -> None:
            if result is None:
                return
            self._save_marked_agent_group(group_name=result.name)

        self.push_screen(  # type: ignore[attr-defined]
            SaveAgentGroupModal(candidate_count=len(agents)),
            on_dismiss,
        )

    def _save_marked_agent_group(self, *, group_name: str | None = None) -> None:
        """Save marked agents as a revivable group and hide them without killing."""
        if not self._marked_agents:
            self.notify("No agents marked", severity="warning")  # type: ignore[attr-defined]
            return

        agents = self._marked_agent_group_candidates()
        if not agents:
            self._marked_agents = set()
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        identities = {agent.identity for agent in agents}
        added = identities - self._dismissed_agents
        group = build_saved_agent_group(agents, group_name=group_name)
        cache_recent_dismissed_agent_group(self, group)
        for identity in identities:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)

        self._dismissed_agents.update(identities)
        self._marked_agents.clear()
        self._apply_dismissal_in_memory(agents)  # type: ignore[attr-defined]

        count = len(agents)
        message = f"Saved and dismissed {count} {plural_agent(count)}"
        notify_after_refresh = getattr(self, "_notify_after_refresh", None)
        if callable(notify_after_refresh):
            notify_after_refresh(message)
        else:
            self.notify(message)  # type: ignore[attr-defined]

        self.call_later(  # type: ignore[attr-defined]
            self._run_marked_agent_group_save_persistence_async,
            list(agents),
            set(self._dismissed_agents),
            added,
            group,
            normalize_saved_group_name(group_name),
        )

    async def _run_marked_agent_group_save_persistence_async(
        self,
        agents: list[Agent],
        dismissed_snapshot: set[AgentIdentity],
        added: set[AgentIdentity],
        group: SavedAgentGroupWire,
        group_name: str | None = None,
    ) -> None:
        """Persist the saved group and dismissed index in a worker thread."""
        identities = {agent.identity for agent in agents}
        if identities & self._dismiss_persistence_inflight:
            return
        self._dismiss_persistence_inflight.update(identities)

        started = time.perf_counter()
        success = True
        try:
            await asyncio.to_thread(
                _persist_marked_agent_group_save,
                agents,
                dismissed_snapshot,
                added,
                group,
                group_name,
            )
        except Exception as exc:
            success = False
            count = len(agents)
            self.notify(  # type: ignore[attr-defined]
                f"Saved {count} {plural_agent(count)} in memory, but group "
                f"archive failed: {exc}. Refresh recommended.",
                severity="error",
            )
            self._schedule_agents_async_refresh(source="mark_error_recovery")  # type: ignore[attr-defined]
        finally:
            self._dismiss_persistence_inflight.difference_update(identities)
            log.debug(
                "marked agent group save persistence: count=%d elapsed=%.3fs",
                len(agents),
                time.perf_counter() - started,
            )
            if success:
                await self._refresh_notification_count_async()  # type: ignore[attr-defined]
