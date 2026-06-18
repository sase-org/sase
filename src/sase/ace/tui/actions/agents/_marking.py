"""Agent marking actions for the ace TUI app."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
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
    _marked_agent_order: list[tuple[AgentType, str, str | None]]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _recent_dismissed_agent_groups: list[SavedAgentGroupWire]
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]]
    _current_group_key: tuple[str, ...] | None

    # -- mark membership + order -------------------------------------------

    def _record_marked_agent(self, identity: AgentIdentity) -> None:
        """Mark *identity*, appending it to the explicit mark order.

        Re-marking a previously-unmarked identity lands it at the end because
        unmarking dropped its order entry first.  A defensive de-dup keeps the
        order list a true ordering even if a caller marks an already-marked
        identity.
        """
        self._marked_agents.add(identity)
        order = getattr(self, "_marked_agent_order", None)
        if order is None:
            order = []
        elif identity in order:
            order.remove(identity)
        order.append(identity)
        self._marked_agent_order = order

    def _forget_marked_agent(self, identity: AgentIdentity) -> None:
        """Unmark *identity*, dropping it from both membership and order."""
        self._marked_agents.discard(identity)
        order = getattr(self, "_marked_agent_order", None)
        if order:
            self._marked_agent_order = [i for i in order if i != identity]

    def _reset_marked_agents(self) -> None:
        """Clear both mark membership and mark order together."""
        self._marked_agents = set()
        self._marked_agent_order = []

    def _forget_marked_agents(self, identities: Iterable[AgentIdentity]) -> None:
        """Drop *identities* from both mark membership and mark order."""
        ids = set(identities)
        if not ids:
            return
        self._marked_agents -= ids
        order = getattr(self, "_marked_agent_order", None)
        if order:
            self._marked_agent_order = [i for i in order if i not in ids]

    def _marked_agents_in_mark_order(self) -> list[Agent]:
        """Return marked, still-live agents in the order they were marked.

        Identities are resolved against ``_agents_with_children``.  Marked
        identities missing from the explicit order list (e.g. set directly by a
        test or a legacy path) are appended afterwards in current display
        order, so mark order is honored without ever dropping a live marked
        agent.
        """
        by_identity: dict[AgentIdentity, Agent] = {}
        for agent in self._agents_with_children:
            by_identity.setdefault(agent.identity, agent)

        result: list[Agent] = []
        seen: set[AgentIdentity] = set()
        for identity in getattr(self, "_marked_agent_order", None) or []:
            if identity in seen or identity not in self._marked_agents:
                continue
            ordered = by_identity.get(identity)
            if ordered is not None:
                result.append(ordered)
                seen.add(identity)
        for agent in self._agents_with_children:
            if agent.identity in self._marked_agents and agent.identity not in seen:
                result.append(agent)
                seen.add(agent.identity)
        return result

    def _toggle_mark_agent(self) -> None:
        """Toggle the mark on the currently-selected agent."""
        agent = self._get_selected_agent()  # type: ignore[attr-defined]
        if agent is None:
            self.notify("No agent selected", severity="warning")  # type: ignore[attr-defined]
            return

        identity = agent.identity
        if identity in self._marked_agents:
            self._forget_marked_agent(identity)
        else:
            self._record_marked_agent(identity)

        # Auto-advance cursor to the next visible agent row (wraparound),
        # including the same unread side effects as ordinary navigation.
        prev_idx = self.current_idx
        selection_moved, new_agent, new_row_updated = self._advance_mark_selection(
            prev_idx
        )

        # Patch the just-marked row in place; the cursor's new position
        # is reflected by the per-panel highlight update so we avoid
        # rebuilding the whole tree for a one-bit mark change.
        patched = new_row_updated and new_agent is agent
        if not patched:
            patched = self._try_patch_agent_row(agent)  # type: ignore[attr-defined]
        if patched and selection_moved:
            # Selection moved off prev_idx and onto current_idx — update
            # the on-screen highlight without a rebuild.
            self._refresh_panel_highlights()  # type: ignore[attr-defined]
            # Also patch the now-selected agent so its name styling
            # reflects the new selection state. Unread acknowledgment
            # already patches the arrival row when it changes state.
            if new_agent is not None and not new_row_updated:
                self._try_patch_agent_row(new_agent)  # type: ignore[attr-defined]
        if not patched:
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

    def _advance_mark_selection(self, prev_idx: int) -> tuple[bool, Agent | None, bool]:
        """Move mark focus to the next visible agent row.

        Marking targets agents, not collapsed banner rows, so auto-advance
        walks ``_agents_visible_order()`` rather than the full selectable
        stop list. When visible-order helpers are unavailable or the
        current agent is hidden, fall back to the legacy raw-list step.

        Returns ``(selection_moved, arrival_agent, arrival_row_updated)``.
        ``arrival_row_updated`` is true when unread acknowledgment already
        patched or refreshed the newly selected row.
        """
        if not self._agents:
            return False, None, False
        if len(self._agents) == 1:
            if not (0 <= prev_idx < len(self._agents)):
                return False, None, False
            new_agent = self._agents[prev_idx]
            self._current_group_key = None
            return False, new_agent, self._acknowledge_mark_selection_arrival(new_agent)

        try:
            visible = self._agents_visible_order()  # type: ignore[attr-defined]
        except Exception:
            visible = []

        target_idx: int | None = None
        if visible:
            try:
                pos = visible.index(prev_idx)
            except ValueError:
                pass
            else:
                target_idx = visible[(pos + 1) % len(visible)]

        if target_idx is None:
            target_idx = (prev_idx + 1) % len(self._agents)

        if not (0 <= target_idx < len(self._agents)):
            return False, None, False

        selection_moved = target_idx != prev_idx
        new_agent = self._agents[target_idx]
        if not selection_moved:
            self._current_group_key = None
            return False, new_agent, self._acknowledge_mark_selection_arrival(new_agent)

        old_agent = (
            self._agents[prev_idx] if 0 <= prev_idx < len(self._agents) else None
        )
        if old_agent is not None:
            arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
            if callable(arm_manual):
                arm_manual(old_agent)

        self.current_idx = target_idx
        self._current_group_key = None
        arrival_row_updated = self._acknowledge_mark_selection_arrival(new_agent)
        return True, new_agent, arrival_row_updated

    def _acknowledge_mark_selection_arrival(self, agent: Agent) -> bool:
        """Run unread arrival side effects for mark auto-advance."""
        arrival_row_updated = False
        ack_unread = getattr(self, "_acknowledge_agent_unread", None)
        if callable(ack_unread):
            arrival_row_updated = bool(ack_unread(agent))
        return arrival_row_updated

    def _clear_agent_marks(self) -> None:
        """Clear every agent mark."""
        if not self._marked_agents:
            self.notify("No marks to clear", severity="warning")  # type: ignore[attr-defined]
            return

        marked_agents = [
            agent for agent in self._agents if agent.identity in self._marked_agents
        ]
        count = len(self._marked_agents)
        self._reset_marked_agents()
        if marked_agents:
            patched_all = True
            for agent in marked_agents:
                if not self._try_patch_agent_row(agent):  # type: ignore[attr-defined]
                    patched_all = False
                    break
            if not patched_all:
                self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        else:
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
            self._forget_marked_agents(stale)

    def _bulk_kill_marked_agents(self) -> None:
        """Kill / dismiss every marked agent after a single confirmation."""
        if not self._marked_agents:
            return

        marked_agents: list[Agent] = [
            a for a in self._agents_with_children if a.identity in self._marked_agents
        ]
        if not marked_agents:
            self._reset_marked_agents()
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        self._present_bulk_kill_modal(marked_agents)

    def _bulk_kill_marked_agents_and_edit(self) -> None:
        """Kill / dismiss marked agents, then edit each one's prompt.

        This is the marked-set branch of ``,x``: when any agent is marked, it
        acts only on the explicitly marked rows, in mark order (rather than the
        single focused row).  Each killed agent's raw prompt is collected up
        front (with the same forced-name-reuse rule as the focused-row path)
        and, on confirmation, seeded into its own prompt pane so the panes
        match the marks one-for-one and follow mark order, not row order.
        """
        if not self._marked_agents:
            self.notify("No agents marked", severity="warning")  # type: ignore[attr-defined]
            return

        # Stale marks are dropped before resolving so panes only ever cover
        # still-live marked rows.
        self._prune_stale_marked_agents()
        marked_agents = self._marked_agents_in_mark_order()
        if not marked_agents:
            self._reset_marked_agents()
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        from sase.agent.retry_prompt import force_name_reuse_in_prompt

        # Collect raw prompts BEFORE any kill mutates the agent list. Marks are
        # preserved on abort so the user can fix the prompt-less row.
        prompts: list[str] = []
        missing = 0
        for agent in marked_agents:
            raw_prompt = agent.get_raw_xprompt_content()
            if raw_prompt is None:
                missing += 1
                continue
            prompts.append(
                force_name_reuse_in_prompt(
                    raw_prompt, replacement_name=agent.agent_name
                )
            )
        if missing:
            suffix = "s" if missing != 1 else ""
            self.notify(  # type: ignore[attr-defined]
                f"{missing} marked agent{suffix} missing a prompt; nothing killed",
                severity="warning",
            )
            return

        first = marked_agents[0]

        def on_confirm(killable: list[Agent], dismissable: list[Agent]) -> None:
            self._do_bulk_kill_agents(killable, dismissable)  # type: ignore[attr-defined]
            self._edit_and_relaunch_agents_bulk(  # type: ignore[attr-defined]
                prompts,
                first.project_file,
                first.cl_name,
                first.is_project_agent,
            )

        self._present_bulk_kill_modal(marked_agents, on_confirm=on_confirm)

    def _present_bulk_kill_modal(
        self,
        agents: list[Agent],
        *,
        header: str | None = None,
        on_confirm: Callable[[list[Agent], list[Agent]], None] | None = None,
    ) -> None:
        """Show the kill/dismiss confirmation modal for an arbitrary agent set.

        Partitions *agents* into killable (live PID + non-dismissable
        status) and dismissable buckets, builds the per-agent description,
        and pushes the matching ``ConfirmKillAllModal`` /
        ``ConfirmDismissAllModal``.  On confirm, routes through *on_confirm*
        (called with the killable/dismissable buckets), defaulting to the same
        ``_do_bulk_kill_agents`` machinery used by the marked-set path.  The
        kill-and-edit flow passes a wrapper that kills first and then mounts the
        prompt stack.
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

        confirm = on_confirm or self._do_bulk_kill_agents  # type: ignore[attr-defined]

        def on_dismiss(confirmed: bool | None) -> None:
            if not confirmed:
                return
            confirm(killable, dismissable)

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
            self._reset_marked_agents()
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
            self._reset_marked_agents()
            self.notify("No marked agents remain", severity="warning")  # type: ignore[attr-defined]
            return

        identities = {agent.identity for agent in agents}
        added = identities - self._dismissed_agents
        group = build_saved_agent_group(
            agents, group_name=group_name, resolve_bundle_paths=False
        )
        cache_recent_dismissed_agent_group(self, group)
        for identity in identities:
            self._agent_status_overrides.pop(identity, None)
            self._agent_pre_question_status.pop(identity, None)

        self._dismissed_agents.update(identities)
        self._reset_marked_agents()
        self._apply_dismissal_in_memory(agents)  # type: ignore[attr-defined]

        count = len(agents)
        message = f"Saved and dismissed {count} {plural_agent(count)}"
        notify_after_refresh = getattr(self, "_notify_after_refresh", None)
        if callable(notify_after_refresh):
            notify_after_refresh(message)
        else:
            self.notify(message)  # type: ignore[attr-defined]

        from ....dismissed_agents import snapshot_dismissed_agents

        self.call_later(  # type: ignore[attr-defined]
            self._run_marked_agent_group_save_persistence_async,
            list(agents),
            snapshot_dismissed_agents(self._dismissed_agents),
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
