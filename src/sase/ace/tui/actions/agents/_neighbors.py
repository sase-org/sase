"""Cached Agents-tab neighbor index helpers."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..navigation._agent_reveal import (
    AgentIdentity,
    prepare_agent_navigation_target,
    reveal_agent_navigation_target,
)
from ._fold_scope import panel_fold_registry, panel_fold_version_signature
from ._navigation_order import rendered_panel_slice

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_groups import GroupingMode
    from ...models.agent_hoods import AgentNeighborIndex, AgentNeighborRow
    from ...models.agent_panels import AgentPanelGroup
    from ...modals.agent_neighbor_modal import AgentNeighborChoice


@dataclass(frozen=True)
class _AgentNeighborPayload:
    """Action payload parallel to one modal choice row."""

    target_identity: AgentIdentity | None = None
    source_identity: AgentIdentity | None = None
    global_idx: int | None = None
    dismissed_agent: Agent | None = None


class AgentNeighborMixin:
    """Mixin that exposes the cached visible neighbor index."""

    _agents: list[Agent]
    _dismissed_agents: set[Any]
    _dismissed_agent_objects: list[Agent]
    _dismiss_revive_epoch: int
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool
    _agent_neighbor_index_cache: tuple[Any, ...] | None
    _current_group_key: tuple[str, ...] | None
    current_idx: int
    current_attempt_number: int | None
    current_tab: str

    def _agent_neighbor_index(self) -> AgentNeighborIndex:
        """Return the cached index of rendered and clan-revealable rows."""
        from ...models.agent_groups import GroupingMode

        panel_group = getattr(self, "_panel_group", None)
        panel_keys = tuple(getattr(panel_group, "panel_keys", (None,)))
        fold_version = panel_fold_version_signature(self, panel_keys)
        grouping_mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        merge_tribe_panels = getattr(self, "_agent_panels_grouped", False)
        dismiss_epoch = getattr(self, "_dismiss_revive_epoch", 0)
        complete = list(getattr(self, "_agents_with_children", ()) or self._agents)
        fold_manager = getattr(self, "_fold_manager", None)
        tree_fold_signature = (
            tuple(
                sorted(
                    (key, level.value) for key, level in fold_manager.snapshot().items()
                )
            )
            if fold_manager is not None
            else ()
        )
        roster_signature = tuple(
            (
                agent.identity,
                agent.agent_name,
                agent.status,
                agent.tribe,
                agent.project_file,
                agent.tree_parent_key,
                agent.is_hidden_step,
                agent.is_clan_container,
                tuple(child.identity for child in agent.runtime_children),
            )
            for agent in complete
        )
        current_signature = tuple(agent.identity for agent in self._agents)
        query_signature = (
            getattr(self, "_agent_search_query", "") or "",
            id(getattr(self, "_agent_content_search_index", None)),
        )
        dismissed_signature = (
            dismiss_epoch,
            frozenset(getattr(self, "_dismissed_agents", set())),
        )
        panel_collapse_signature = frozenset(
            getattr(self, "_collapsed_panel_keys", set())
        )

        cached = getattr(self, "_agent_neighbor_index_cache", None)
        if (
            cached is not None
            and cached[0] == current_signature
            and cached[1] == roster_signature
            and cached[2] == panel_keys
            and cached[3] == merge_tribe_panels
            and cached[4] == grouping_mode
            and cached[5] == fold_version
            and cached[6] == tree_fold_signature
            and cached[7] == query_signature
            and cached[8] == dismissed_signature
            and cached[9] == panel_collapse_signature
        ):
            return cached[10]

        index = self._build_agent_neighbor_index()
        self._agent_neighbor_index_cache = (
            current_signature,
            roster_signature,
            panel_keys,
            merge_tribe_panels,
            grouping_mode,
            fold_version,
            tree_fold_signature,
            query_signature,
            dismissed_signature,
            panel_collapse_signature,
            index,
        )
        return index

    def _build_agent_neighbor_index(self) -> AgentNeighborIndex:
        """Build a fresh neighbor index from rendered and prospective rows."""
        from ...models.agent_hoods import AgentNeighborIndex

        return AgentNeighborIndex.from_visible_rows(
            list(self._revealable_agent_neighbor_rows()),
            dismissed_agents=self._active_dismissed_agent_objects(),
        )

    def _revealable_agent_neighbor_rows(self) -> Iterator[AgentNeighborRow]:
        """Yield the rendered union plus rows hidden only by clan folding."""
        from ...models.agent_hoods import AgentNeighborRow, agent_hood
        from ._prospective_clan import prospective_clan_projection

        visible = list(self._visible_agent_neighbor_rows())
        complete = list(getattr(self, "_agents_with_children", ()) or self._agents)
        projection = prospective_clan_projection(self, complete)
        visible_identities = {row.identity for row in visible}
        rows: list[AgentNeighborRow] = []
        fallback_offset = len(projection.display_order_by_identity)
        for fallback_order, row in enumerate(visible):
            rows.append(
                AgentNeighborRow(
                    global_idx=row.global_idx,
                    panel_idx=row.panel_idx,
                    agent=row.agent,
                    hood=row.hood,
                    panel_key=row.panel_key,
                    display_order=projection.display_order_by_identity.get(
                        row.identity,
                        fallback_offset + fallback_order,
                    ),
                )
            )
        for target in projection.members.values():
            if target.identity in visible_identities:
                continue
            rows.append(
                AgentNeighborRow(
                    global_idx=None,
                    panel_idx=target.panel_idx,
                    panel_key=target.panel_key,
                    agent=target.agent,
                    hood=agent_hood(target.agent),
                    display_order=target.display_order,
                    clan_fold_key=target.clan_fold_key,
                )
            )
        yield from sorted(rows, key=lambda row: row.display_order)

    def _active_dismissed_agent_objects(self) -> tuple[Agent, ...]:
        """Return same-session dismissed objects whose identities are still hidden."""
        dismissed_ids: set[Any] = set(getattr(self, "_dismissed_agents", set()))
        if not dismissed_ids:
            return ()

        active: list[Agent] = []
        seen: set[Any] = set()
        for agent in getattr(self, "_dismissed_agent_objects", ()):
            identity = agent.identity
            if identity in seen or identity not in dismissed_ids:
                continue
            active.append(agent)
            seen.add(identity)
        return tuple(active)

    def _visible_agent_neighbor_rows(self) -> Iterator[AgentNeighborRow]:
        """Yield visible agent rows across every rendered Agents-tab panel."""
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ...models.agent_hoods import AgentNeighborRow, agent_hood
        from ...models.agent_panels import agent_is_rendered_in_agents_panel

        mode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        panel_group = getattr(self, "_panel_group", None)
        display_order = 0

        if panel_group is None:
            registry = panel_fold_registry(self, None)
            global_indices = [
                idx
                for idx, agent in enumerate(self._agents)
                if agent_is_rendered_in_agents_panel(agent)
            ]
            panel_agents = [self._agents[idx] for idx in global_indices]
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            for entry in tree:
                if entry.kind == "agent" and entry.agent_idx is not None:
                    local_idx = entry.agent_idx
                    yield AgentNeighborRow(
                        global_idx=global_indices[local_idx],
                        panel_idx=0,
                        agent=panel_agents[local_idx],
                        hood=agent_hood(panel_agents[local_idx]),
                        panel_key=None,
                        display_order=display_order,
                    )
                    display_order += 1
            return

        for panel_idx, key in enumerate(panel_group.panel_keys):
            registry = panel_fold_registry(self, key)
            global_indices, panel_agents = rendered_panel_slice(self, key)
            tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
            for entry in tree:
                if entry.kind == "agent" and entry.agent_idx is not None:
                    local_idx = entry.agent_idx
                    yield AgentNeighborRow(
                        global_idx=global_indices[local_idx],
                        panel_idx=panel_idx,
                        agent=panel_agents[local_idx],
                        hood=agent_hood(panel_agents[local_idx]),
                        panel_key=key,
                        display_order=display_order,
                    )
                    display_order += 1

    def _start_agent_neighbor_navigation(self) -> None:
        """Jump to, revive, or choose from related agents of the selected agent."""
        if getattr(self, "current_tab", None) != "agents":
            return
        if getattr(self, "_current_group_key", None) is not None:
            return
        if not self._agents or not (0 <= self.current_idx < len(self._agents)):
            return

        selected = self._get_selected_agent()  # type: ignore[attr-defined]
        if selected is None:
            return

        index = self._agent_neighbor_index()
        selected_target = index.target_for_global_idx(self.current_idx)
        if selected_target is None:
            return
        ancestors = index.ancestor_targets_for(selected_target.identity)
        descendants = index.descendant_targets_for(selected_target.identity)
        hood_neighbor_groups = index.hood_neighbor_target_groups_for(
            selected_target.identity
        )
        neighbors = index.neighbor_targets_for(selected_target.identity)
        dismissed_descendants = self._dismissed_descendant_agents(selected)
        if (
            not ancestors
            and not neighbors
            and not descendants
            and not dismissed_descendants
        ):
            return

        guard = getattr(self, "_guard_agent_navigation_for_artifact_file_viewer", None)
        if callable(guard) and guard():
            return

        related_count = (
            len(ancestors)
            + len(neighbors)
            + len(descendants)
            + len(dismissed_descendants)
        )
        if related_count == 1 and not dismissed_descendants:
            target = (
                ancestors[0]
                if ancestors
                else descendants[0]
                if descendants
                else neighbors[0]
            )
            self._focus_agent_neighbor_by_identity(
                target.identity,
                source_identity=selected.identity,
                display_global_idx=target.global_idx,
            )
            return

        choices, payloads = self._agent_neighbor_choices(
            ancestors,
            descendants,
            dismissed_descendants,
            hood_neighbor_groups,
            selected,
        )
        if not choices:
            return

        from ...modals import AgentNeighborModal

        def _on_neighbor_selected(choice_idx: int | None) -> None:
            if choice_idx is None or not 0 <= choice_idx < len(payloads):
                return
            payload = payloads[choice_idx]
            if payload.target_identity is not None:
                self._focus_agent_neighbor_by_identity(
                    payload.target_identity,
                    source_identity=payload.source_identity,
                    display_global_idx=payload.global_idx,
                )
                return
            if payload.dismissed_agent is not None:
                revive = getattr(self, "_do_revive_agent", None)
                if callable(revive):
                    revive(payload.dismissed_agent)

        self.push_screen(  # type: ignore[attr-defined]
            AgentNeighborModal(
                selected.agent_name or selected.display_name,
                choices,
            ),
            _on_neighbor_selected,
        )

    def _focus_agent_neighbor_by_identity(
        self,
        target_identity: AgentIdentity,
        *,
        source_identity: AgentIdentity | None = None,
        display_global_idx: int | None = None,
    ) -> bool:
        """Revalidate, reveal, and focus a neighbor by stable identity."""
        if getattr(self, "current_tab", None) != "agents":
            return False

        guard = getattr(self, "_guard_agent_navigation_for_artifact_file_viewer", None)
        if callable(guard) and guard():
            return False

        # Modal callbacks and footer fast paths never trust their old numeric
        # payload. Rebuild/reuse the current cached projection and require the
        # target to remain related and revealable from the same source row.
        index = self._agent_neighbor_index()
        target = index.target_for_identity(target_identity)
        if target is None:
            return False
        if source_identity is not None:
            selected = self._get_selected_agent()  # type: ignore[attr-defined]
            if selected is None or selected.identity != source_identity:
                return False
            if target_identity not in index.related_target_identities_for(
                source_identity
            ):
                return False

        plan, _failure = prepare_agent_navigation_target(
            self,
            target_identity,
            require_current=target.global_idx is not None,
        )
        if plan is None:
            return False

        panel_group = getattr(self, "_panel_group", None)
        old_focused_idx = panel_group.focused_idx if panel_group is not None else None
        old_idx = self.current_idx
        old_group_key = getattr(self, "_current_group_key", None)
        old_agent = (
            self._agents[old_idx]
            if old_group_key is None and 0 <= old_idx < len(self._agents)
            else None
        )
        back_stack = list(getattr(self, "_entry_jump_agents_anchor_stack", ()))
        forward_stack = list(
            getattr(self, "_entry_jump_agents_forward_anchor_stack", ())
        )
        save_jump_anchor = getattr(self, "_save_agents_jump_anchor", None)
        if callable(save_jump_anchor):
            save_jump_anchor()

        outcome = reveal_agent_navigation_target(self, plan)
        reveal = outcome.result
        if reveal is None:
            self._restore_agent_neighbor_jump_history(back_stack, forward_stack)
            return False
        if old_agent is not None and reveal.tree_changed:
            rebase_anchor = getattr(self, "_rebase_latest_agents_jump_anchor", None)
            if callable(rebase_anchor):
                rebase_anchor(old_agent.identity)

        # ``display_global_idx`` is deliberately not used for selection. It is
        # retained in the payload solely as display-time metadata so a modal
        # callback can never drift to whichever row later occupies that slot.
        del display_global_idx

        panel_group = getattr(self, "_panel_group", None)
        if (
            panel_group is not None
            and 0 <= reveal.panel_idx < len(panel_group.panel_keys)
            and reveal.panel_idx != panel_group.focused_idx
        ):
            panel_group.focused_idx = reveal.panel_idx

        if old_agent is not None and old_agent.identity != target_identity:
            arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
            if callable(arm_manual):
                arm_manual(old_agent)

        self._current_group_key = None  # type: ignore[attr-defined]
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None  # type: ignore[attr-defined]
        self.current_idx = reveal.target_idx

        ack_unread = getattr(self, "_acknowledge_agent_unread", None)
        if callable(ack_unread):
            ack_unread(reveal.target_agent)

        self._refresh_agent_neighbor_jump_views(
            old_focused_idx=old_focused_idx,
            structural_changed=reveal.structural_changed,
        )
        return True

    def _restore_agent_neighbor_jump_history(
        self,
        back_stack: list[object],
        forward_stack: list[object],
    ) -> None:
        """Undo a tentative anchor save when a stable target cannot resolve."""
        current_back = getattr(self, "_entry_jump_agents_anchor_stack", None)
        if isinstance(current_back, list):
            current_back[:] = back_stack
        current_forward = getattr(
            self,
            "_entry_jump_agents_forward_anchor_stack",
            None,
        )
        if isinstance(current_forward, list):
            current_forward[:] = forward_stack

    def _refresh_agent_neighbor_jump_views(
        self,
        *,
        old_focused_idx: int | None,
        structural_changed: bool,
    ) -> None:
        """Rebuild only for a reveal; otherwise retain selective repainting."""
        if structural_changed:
            refresh_display = getattr(self, "_refresh_agents_display", None)
            if callable(refresh_display):
                try:
                    refresh_display(list_changed=True, defer_detail=True)
                except TypeError:
                    refresh_display(list_changed=True)
            return

        panel_group = getattr(self, "_panel_group", None)
        focused_changed = (
            panel_group is not None
            and old_focused_idx is not None
            and old_focused_idx != panel_group.focused_idx
        )
        refresh_focused_panel = getattr(self, "_refresh_focused_agent_panel", None)
        if focused_changed and callable(refresh_focused_panel):
            refresh_focused_panel(old_focused_idx=old_focused_idx)
        else:
            refresh_highlights = getattr(self, "_refresh_panel_highlights", None)
            if callable(refresh_highlights):
                refresh_highlights()
            else:
                refresh_display = getattr(self, "_refresh_agents_display", None)
                if callable(refresh_display):
                    refresh_display(list_changed=False)

        update_info = getattr(self, "_update_agents_info_panel", None)
        if callable(update_info):
            update_info()
        apply_immediate = getattr(self, "_apply_agent_detail_immediate", None)
        if callable(apply_immediate):
            apply_immediate()
        debouncer = getattr(self, "_agent_detail_debouncer", None)
        fire_detail = getattr(self, "_fire_debounced_detail_update", None)
        if debouncer is not None and callable(fire_detail):
            debouncer.schedule(fire_detail)

    def _agent_neighbor_choices(
        self,
        ancestors: tuple[AgentNeighborRow, ...],
        descendants: tuple[AgentNeighborRow, ...],
        dismissed_descendants: tuple[Agent, ...],
        hood_neighbor_groups: tuple[tuple[str, tuple[AgentNeighborRow, ...]], ...],
        selected: Agent,
    ) -> tuple[list[AgentNeighborChoice], list[_AgentNeighborPayload]]:
        """Build modal choices and action payloads for related rows."""
        from ...models.agent_hoods import agent_name_key
        from ...modals.agent_neighbor_modal import AgentNeighborChoice

        choices: list[AgentNeighborChoice] = []
        payloads: list[_AgentNeighborPayload] = []

        for target in ancestors:
            agent = target.agent
            choices.append(
                AgentNeighborChoice(
                    agent_name=agent.agent_name or agent.display_name,
                    display_name=agent.display_name,
                    status=agent.status,
                    panel_label=self._agent_neighbor_panel_label(target),
                    time_hint=self._agent_neighbor_time_hint(agent),
                    group="ancestor",
                    dismissed=False,
                    global_idx=target.global_idx,
                )
            )
            payloads.append(
                _AgentNeighborPayload(
                    target_identity=agent.identity,
                    source_identity=selected.identity,
                    global_idx=target.global_idx,
                )
            )

        descendant_items: list[tuple[str, bool, Agent, AgentNeighborRow | None]] = []
        for target in descendants:
            agent = target.agent
            key = agent_name_key(agent)
            if key is None:
                continue
            descendant_items.append((key, False, agent, target))
        for agent in dismissed_descendants:
            key = agent_name_key(agent)
            if key is None:
                continue
            descendant_items.append((key, True, agent, None))

        for _key, dismissed, agent, descendant_target in sorted(
            descendant_items,
            key=lambda item: (
                item[0],
                item[1],
                (item[2].display_name or "").casefold(),
            ),
        ):
            choices.append(
                AgentNeighborChoice(
                    agent_name=agent.agent_name or agent.display_name,
                    display_name=agent.display_name,
                    status=agent.status,
                    panel_label=(
                        self._agent_neighbor_dismissed_panel_label(agent)
                        if dismissed
                        else self._agent_neighbor_panel_label(descendant_target)
                    ),
                    time_hint=self._agent_neighbor_time_hint(agent),
                    group="descendant",
                    dismissed=dismissed,
                    global_idx=(
                        descendant_target.global_idx
                        if descendant_target is not None
                        else None
                    ),
                )
            )
            payloads.append(
                _AgentNeighborPayload(
                    target_identity=(agent.identity if not dismissed else None),
                    source_identity=(selected.identity if not dismissed else None),
                    global_idx=(
                        descendant_target.global_idx
                        if descendant_target is not None
                        else None
                    ),
                    dismissed_agent=agent if dismissed else None,
                )
            )

        raw_hood_by_key = self._agent_neighbor_display_hoods(selected)
        for hood, neighbor_targets in hood_neighbor_groups:
            hood_label = raw_hood_by_key.get(hood, hood)
            for target in neighbor_targets:
                agent = target.agent
                choices.append(
                    AgentNeighborChoice(
                        agent_name=agent.agent_name or agent.display_name,
                        display_name=agent.display_name,
                        status=agent.status,
                        panel_label=self._agent_neighbor_panel_label(target),
                        time_hint=self._agent_neighbor_time_hint(agent),
                        group="neighbor",
                        hood=hood_label,
                        dismissed=False,
                        global_idx=target.global_idx,
                    )
                )
                payloads.append(
                    _AgentNeighborPayload(
                        target_identity=agent.identity,
                        source_identity=selected.identity,
                        global_idx=target.global_idx,
                    )
                )
        return choices, payloads

    def _dismissed_descendant_agents(self, selected: Agent) -> tuple[Agent, ...]:
        """Return active dismissed descendants of ``selected`` sorted by name."""
        from ...models.agent_hoods import agent_name_key, is_agent_descendant

        selected_name = selected.agent_name
        if selected_name is None:
            return ()

        descendants = [
            agent
            for agent in self._active_dismissed_agent_objects()
            if is_agent_descendant(agent.agent_name, selected_name)
        ]
        return tuple(
            sorted(
                descendants,
                key=lambda agent: (
                    agent_name_key(agent) or "",
                    (agent.display_name or "").casefold(),
                ),
            )
        )

    def _agent_neighbor_display_hoods(self, agent: Agent) -> dict[str, str]:
        """Map selected-agent hood keys to labels preserving displayed case."""
        parts = (agent.agent_name or "").split(".")
        return {
            ".".join(parts[:depth]).casefold(): ".".join(parts[:depth])
            for depth in range(1, len(parts) + 1)
            if all(parts[:depth])
        }

    def _agent_neighbor_panel_label(
        self,
        target: AgentNeighborRow | None,
    ) -> str:
        """Return a compact label for the tribe panel containing a neighbor."""
        if getattr(self, "_agent_panels_grouped", False):
            return "all"
        if target is None:
            return "panel"
        key = target.panel_key
        return "(no tribe)" if key is None else f"@{key}"

    def _agent_neighbor_dismissed_panel_label(self, agent: Agent) -> str:
        """Return a compact tribe label for a dismissed descendant row."""
        if getattr(self, "_agent_panels_grouped", False):
            return "all"
        tribe = agent.tribe
        return f"@{tribe}" if tribe else "(no tribe)"

    def _agent_neighbor_time_hint(self, agent: Agent) -> str:
        """Return a compact timestamp/runtime hint for a neighbor row."""
        from ...models.agent import compute_row_runtime

        timestamp, elapsed = compute_row_runtime(agent)
        if timestamp is not None:
            date_prefix, time_text = timestamp
            finished = f"{date_prefix}{time_text}".strip()
            return f"{finished} {elapsed or ''}".strip()
        if elapsed:
            return elapsed
        if agent.stop_time is not None:
            return agent.stop_time.strftime("%H:%M")
        if agent.run_start_time is not None:
            return agent.run_start_time.strftime("%H:%M")
        if agent.start_time is not None:
            return agent.start_time.strftime("%H:%M")
        return ""
