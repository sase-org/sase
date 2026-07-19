"""Agent marking actions for the ace TUI app."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Literal

from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
)

from ._cleanup_tasks import CleanupTaskOutcome
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

    from sase.notifications import (
        dismiss_agent_completion_notifications_matching_agents,
    )

    dismiss_agent_completion_notifications_matching_agents(
        [{"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix} for agent in agents]
    )

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
        """Toggle the mark on the selected agent or focused group."""
        if self._current_group_key is not None and self._toggle_mark_focused_group():
            return

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

    def _toggle_mark_focused_group(self) -> bool:
        """Toggle all top-level members of the focused collapsed group.

        Returns ``False`` when the stored group key is stale, allowing the
        caller to fall through to the single-agent path just like kill/dismiss.
        """
        from ._group_focus import get_focused_agent_group, top_level_group_agents

        group = get_focused_agent_group(self)
        if group is None:
            return False

        members = top_level_group_agents(group, self._agents)
        if not members:
            self.notify("No agents in group", severity="warning")  # type: ignore[attr-defined]
            return True

        identities = [agent.identity for agent in members]
        if all(identity in self._marked_agents for identity in identities):
            for identity in identities:
                self._forget_marked_agent(identity)
        else:
            for identity in identities:
                self._record_marked_agent(identity)

        prev_idx = self.current_idx
        prev_group_key = self._current_group_key
        self._advance_mark_group_selection(prev_idx, prev_group_key)
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]
        return True

    def _advance_mark_group_selection(
        self,
        prev_idx: int,
        prev_group_key: tuple[str, ...] | None,
    ) -> None:
        """Move focus to the next selectable stop after a group mark."""
        if not self._agents or prev_group_key is None:
            return

        try:
            stops = self._panel_navigation_stops()  # type: ignore[attr-defined]
        except Exception:
            stops = []
        if not stops:
            return

        stop_maps = getattr(self, "_panel_navigation_stop_maps", None)
        agent_positions: dict[int, int] = {}
        banner_positions: dict[tuple[str, ...], int] = {}
        if callable(stop_maps):
            try:
                agent_positions, banner_positions = stop_maps()
            except Exception:
                agent_positions, banner_positions = {}, {}
        if not banner_positions:
            for stop_pos, (kind, payload) in enumerate(stops):
                if kind == "banner":
                    assert isinstance(payload, tuple)
                    banner_positions[payload] = stop_pos
                else:
                    assert isinstance(payload, int)
                    agent_positions[payload] = stop_pos

        current_pos = banner_positions.get(prev_group_key)
        if current_pos is None:
            current_pos = agent_positions.get(prev_idx)
        if current_pos is None:
            return

        kind, payload = stops[(current_pos + 1) % len(stops)]
        if kind == "banner":
            assert isinstance(payload, tuple)
            self._current_group_key = payload
            self._set_current_idx_to_group_anchor(payload)
            return

        assert isinstance(payload, int)
        self.current_idx = payload
        self._current_group_key = None
        if 0 <= payload < len(self._agents):
            self._acknowledge_mark_selection_arrival(self._agents[payload])

    def _set_current_idx_to_group_anchor(self, group_key: tuple[str, ...]) -> None:
        """Set ``current_idx`` to a banner group's first backing agent."""
        from ._group_focus import get_focused_agent_group

        old_key = self._current_group_key
        self._current_group_key = group_key
        try:
            group = get_focused_agent_group(self)
        finally:
            self._current_group_key = old_key
        if group is None:
            return
        for idx in group.agent_indices:
            if 0 <= idx < len(self._agents):
                self.current_idx = idx
                return

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
        refresh_summary = getattr(self, "_refresh_tribe_summary_only", None)
        if not callable(refresh_summary) or not refresh_summary():
            refresh_footer = getattr(self, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh_footer):
                refresh_footer()
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

        from ..agent_workflow._entry_name_prompts import (
            prepare_kill_and_edit_prompt,
        )

        # Collect raw prompts BEFORE any kill mutates the agent list. Marks are
        # preserved on abort so the user can fix the prompt-less row.
        prompts: list[str] = []
        missing = 0
        for agent in marked_agents:
            raw_prompt = agent.get_raw_xprompt_content()
            if raw_prompt is None:
                missing += 1
                continue
            prompts.append(prepare_kill_and_edit_prompt(raw_prompt, agent.agent_name))
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
        from ._clan_cleanup import clan_members_for_container

        # A clan row is a synthetic selection target, never a persistence or
        # process target. Expand it to its real loaded rows and deduplicate in
        # tree order so marked/group cleanup uses the same cascade as focused x.
        expanded_agents: list[Agent] = []
        seen: set[tuple[AgentType, str, str | None]] = set()
        for agent in agents:
            candidates = (
                clan_members_for_container(agent, self._agents_with_children)
                if getattr(agent, "is_clan_container", False)
                else [agent]
            )
            for candidate in candidates:
                if candidate.identity in seen:
                    continue
                seen.add(candidate.identity)
                expanded_agents.append(candidate)
        agents = expanded_agents

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
        clear_completion_notifications = getattr(
            self,
            "_dismiss_agent_completion_notifications_for_dismissed_agents",
            None,
        )
        if callable(clear_completion_notifications):
            clear_completion_notifications(agents)

        count = len(agents)
        message = f"Saved and dismissed {count} {plural_agent(count)}"
        notify_after_refresh = getattr(self, "_notify_after_refresh", None)
        if callable(notify_after_refresh):
            notify_after_refresh(message)
        else:
            self.notify(message)  # type: ignore[attr-defined]

        from ....dismissed_agents import snapshot_dismissed_agents

        self._submit_marked_group_save_persistence_task(
            list(agents),
            snapshot_dismissed_agents(self._dismissed_agents),
            added,
            group,
            normalize_saved_group_name(group_name),
        )

    def _submit_marked_group_save_persistence_task(
        self,
        agents: list[Agent],
        dismissed_snapshot: set[AgentIdentity],
        added: set[AgentIdentity],
        group: SavedAgentGroupWire,
        group_name: str | None = None,
    ) -> None:
        """Submit marked-group save persistence as a tracked background task."""
        identities = {agent.identity for agent in agents}
        if identities & self._dismiss_persistence_inflight:
            return
        self._dismiss_persistence_inflight.update(identities)

        count = len(agents)

        def _worker() -> CleanupTaskOutcome:
            started = time.perf_counter()
            try:
                _persist_marked_agent_group_save(
                    agents,
                    dismissed_snapshot,
                    added,
                    group,
                    group_name,
                )
            except Exception as exc:
                return CleanupTaskOutcome(
                    message=(
                        f"Saved {count} {plural_agent(count)} in memory, but group "
                        f"archive failed: {exc}. Refresh recommended."
                    ),
                    severity="error",
                    notify=True,
                    schedule_agents_refresh_source="mark_error_recovery",
                )
            finally:
                self._dismiss_persistence_inflight.difference_update(identities)
                log.debug(
                    "marked agent group save persistence: count=%d elapsed=%.3fs",
                    count,
                    time.perf_counter() - started,
                )
            return CleanupTaskOutcome(
                message=f"Saved {count} {plural_agent(count)}",
                refresh_notifications=True,
            )

        if not self._submit_cleanup_task(  # type: ignore[attr-defined]
            task_type="save",
            display_name=f"save {count} {plural_agent(count)}",
            cl_name="",
            project_file="",
            task_callable=_worker,
        ):
            self._dismiss_persistence_inflight.difference_update(identities)
