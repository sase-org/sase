"""Agent mark state and navigation for the ace TUI app."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal

from ._dismiss_cleanup import AgentIdentity

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

TabName = Literal["changespecs", "agents", "axe"]


class AgentMarkNavigationMixin:
    """Manage agent marks and navigation after marking actions."""

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _marked_agent_order: list[tuple[AgentType, str, str | None]]
    _current_group_key: tuple[str, ...] | None

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
