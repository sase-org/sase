"""Digit-key navigation for numbered clan and family member rosters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._types import NavigationMixinBase

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_panels import PanelKey
    from ...widgets.prompt_panel._member_roster import MemberJumpMap

type MemberIdentity = tuple["AgentType", str, str | None]


class MemberJumpNavigationMixin(NavigationMixinBase):
    """Handle the fixed digit hints rendered in container member rosters."""

    def _selected_member_jump_container(self) -> Agent | None:
        """Return the selected clan/family container, excluding banner focus."""
        if (
            self.current_tab != "agents"
            or getattr(self, "_current_group_key", None) is not None
        ):
            return None
        get_selected = getattr(self, "_get_selected_agent", None)
        if not callable(get_selected):
            return None
        agent = get_selected()
        if agent is None or not (
            agent.is_clan_container or agent.is_family_container_row
        ):
            return None
        return agent

    def _member_jump_map_for(
        self,
        container: Agent,
    ) -> MemberJumpMap | None:
        """Return only a map that belongs to the live selected container."""
        jump_map = getattr(self, "_member_jump_maps", {}).get(container.identity)
        if jump_map is None or jump_map.container_identity != container.identity:
            return None
        return jump_map

    def _update_member_jump_footer(self, first_digit: str) -> None:
        """Show the pending two-digit indicator without rebuilding detail."""
        try:
            from ...widgets import KeybindingFooter

            footer = self.query_one("#keybinding-footer", KeybindingFooter)  # type: ignore[attr-defined]
            footer.update_member_jump_bindings(first_digit)
        except Exception:
            pass

    def _cancel_member_jump_pending(self, *, refresh_footer: bool = True) -> bool:
        """Clear a buffered first digit and optionally restore normal bindings."""
        if getattr(self, "_member_jump_pending_digit", None) is None:
            return False
        self._member_jump_pending_digit = None  # type: ignore[attr-defined]
        self._member_jump_pending_container_identity = None  # type: ignore[attr-defined]
        if refresh_footer and self.current_tab == "agents":
            refresh = getattr(self, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh):
                refresh()
        return True

    def _notify_member_jump(self, message: str) -> None:
        """Show a deliberately brief member-navigation notification."""
        self.notify(message, timeout=1.5)  # type: ignore[attr-defined]

    def _current_member_target_is_valid(
        self,
        container: Agent,
        target_identity: MemberIdentity,
    ) -> bool:
        """Reject maps whose target no longer belongs to the container."""
        if container.is_clan_container:
            return any(
                member.identity == target_identity
                for member in container.runtime_children
                if not member.is_clan_container
            )
        if target_identity == container.identity:
            return True
        return any(
            member.identity == target_identity
            for member in container.followup_agents
            if not member.is_synthetic_planner and not member.agent_family_parallel
        )

    def _member_jump_target(
        self,
        container: Agent,
        jump_map: MemberJumpMap,
        number: str,
    ) -> MemberIdentity | None:
        """Resolve and revalidate one visible number from a published map."""
        target = next(
            (target for target in jump_map.targets if target.number == number),
            None,
        )
        if target is None:
            self._notify_member_jump(f"No member {number}")
            return None
        if not self._current_member_target_is_valid(
            container,
            target.member_identity,
        ):
            self._notify_member_jump("Member roster changed; jump cancelled")
            return None
        return target.member_identity

    def _handle_member_jump_key(self, key: str) -> bool:
        """Handle a digit, pending second digit, or pending cancellation.

        A non-digit key while pending clears the buffer and returns ``False``
        so Textual can process that key normally.
        """
        pending_digit = getattr(self, "_member_jump_pending_digit", None)
        if pending_digit is not None:
            if key == "escape":
                self._cancel_member_jump_pending()
                return True
            if key not in "0123456789":
                self._cancel_member_jump_pending()
                return False

            pending_container = getattr(
                self,
                "_member_jump_pending_container_identity",
                None,
            )
            self._cancel_member_jump_pending(refresh_footer=False)
            container = self._selected_member_jump_container()
            if container is None or container.identity != pending_container:
                self._notify_member_jump("Member selection changed; jump cancelled")
                self._refresh_member_jump_footer_after_action()
                return True
            jump_map = self._member_jump_map_for(container)
            if jump_map is None:
                self._notify_member_jump("Member roster changed; jump cancelled")
                self._refresh_member_jump_footer_after_action()
                return True
            target_identity = self._member_jump_target(
                container,
                jump_map,
                f"{pending_digit}{key}",
            )
            if target_identity is not None:
                self._reveal_agent_row(target_identity)
            self._refresh_member_jump_footer_after_action()
            return True

        if key not in "0123456789":
            return False
        container = self._selected_member_jump_container()
        if container is None:
            return False
        guard = getattr(self, "_guard_agent_navigation_for_artifact_file_viewer", None)
        if callable(guard) and guard():
            return False

        jump_map = self._member_jump_map_for(container)
        if jump_map is None or not jump_map.targets:
            self._notify_member_jump("Member roster is not ready")
            return True
        if len(jump_map.targets[0].number) == 2:
            self._member_jump_pending_digit = key  # type: ignore[attr-defined]
            self._member_jump_pending_container_identity = container.identity  # type: ignore[attr-defined]
            self._update_member_jump_footer(key)
            return True

        target_identity = self._member_jump_target(container, jump_map, key)
        if target_identity is not None:
            self._reveal_agent_row(target_identity)
        return True

    def _refresh_member_jump_footer_after_action(self) -> None:
        """Restore normal footer bindings after a completed/cancelled number."""
        refresh = getattr(self, "_refresh_agent_footer_bindings_only", None)
        if callable(refresh):
            refresh()

    def _expand_target_tree_ancestors(
        self,
        target_identity: MemberIdentity,
    ) -> bool:
        """Expand the bounded agent-tree ancestor chain for ``target_identity``."""
        from ...models._agent_tree import (
            agent_parent_fold_key,
            tree_parent_lookup,
        )
        from ...models.fold_state import FoldLevel

        complete = list(getattr(self, "_agents_with_children", None) or self._agents)
        target = next(
            (agent for agent in complete if agent.identity == target_identity),
            None,
        )
        if target is None:
            return False

        parents = tree_parent_lookup(complete)
        current = target
        visited: set[int] = set()
        for _ in range(len(complete) + 1):
            current_id = id(current)
            if current_id in visited:
                return False
            visited.add(current_id)
            parent_key = agent_parent_fold_key(current)
            if parent_key is None:
                return True
            parent = parents.get(parent_key)
            if parent is None:
                return False

            required = (
                FoldLevel.FULLY_EXPANDED
                if current.is_hidden_step and not parent_key.startswith("clan:")
                else FoldLevel.EXPANDED
            )
            while self._fold_manager.get(parent_key) != required:  # type: ignore[attr-defined]
                if not self._fold_manager.expand(parent_key):  # type: ignore[attr-defined]
                    break
            if self._fold_manager.get(parent_key) == FoldLevel.COLLAPSED:  # type: ignore[attr-defined]
                return False
            if (
                required == FoldLevel.FULLY_EXPANDED
                and self._fold_manager.get(parent_key) != required  # type: ignore[attr-defined]
            ):
                return False
            current = parent
        return False

    def _target_panel_context(
        self,
        target_idx: int,
    ) -> tuple[int | None, PanelKey] | None:
        """Resolve the target's panel index and stable key after refiltering."""
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return (None, None)
        keys_per_agent = self._panel_keys_per_agent()  # type: ignore[attr-defined]
        if not (0 <= target_idx < len(keys_per_agent)):
            return None
        panel_key = keys_per_agent[target_idx]
        try:
            return (panel_group.panel_keys.index(panel_key), panel_key)
        except ValueError:
            return None

    def _expand_target_groups(
        self,
        target_idx: int,
        panel_key: PanelKey,
    ) -> bool:
        """Expand only the rendered grouping banners enclosing the target."""
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ...models.group_fold import GroupFoldRegistry
        from ..agents._fold_scope import panel_fold_registry
        from ..agents._navigation_order import rendered_panel_slice

        global_indices, panel_agents = rendered_panel_slice(self, panel_key)
        try:
            local_idx = global_indices.index(target_idx)
        except ValueError:
            return False

        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        complete_tree = build_agent_tree(
            panel_agents,
            fold_registry=GroupFoldRegistry(),
            mode=mode,
        )
        enclosing_keys = [
            entry.group.group_key
            for entry in complete_tree
            if entry.kind == "group"
            and entry.group is not None
            and local_idx in entry.group.agent_indices
        ]
        registry = panel_fold_registry(self, panel_key)
        changed = False
        for group_key in enclosing_keys:
            if registry is not None and registry.expand(group_key):
                changed = True
                persist = getattr(self, "_persist_group_fold_change", None)
                if callable(persist):
                    persist(group_key, collapsed=False)
        return changed

    def _target_is_visible_in_panel(
        self,
        target_idx: int,
        panel_key: PanelKey,
    ) -> bool:
        """Confirm the expanded in-panel tree now renders the target row."""
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ..agents._fold_scope import panel_fold_registry
        from ..agents._navigation_order import rendered_panel_slice

        global_indices, panel_agents = rendered_panel_slice(self, panel_key)
        try:
            local_idx = global_indices.index(target_idx)
        except ValueError:
            return False
        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        tree = build_agent_tree(
            panel_agents,
            fold_registry=panel_fold_registry(self, panel_key),
            mode=mode,
        )
        return any(
            entry.kind == "agent" and entry.agent_idx == local_idx for entry in tree
        )

    def _reveal_agent_row(self, target_identity: MemberIdentity) -> bool:
        """Reveal a roster target through folds, then select it by identity."""
        complete = list(getattr(self, "_agents_with_children", None) or self._agents)
        if not any(agent.identity == target_identity for agent in complete):
            self._notify_member_jump("Member roster changed; jump cancelled")
            return False

        save_anchor = getattr(self, "_save_agents_jump_anchor", None)
        if callable(save_anchor):
            save_anchor()
        if not self._expand_target_tree_ancestors(target_identity):
            self._notify_member_jump("Member is no longer available")
            return False

        invalidate = getattr(self, "_invalidate_agent_panel_cache", None)
        if callable(invalidate):
            invalidate()
        refilter = getattr(self, "_refilter_agents", None)
        if not callable(refilter):
            self._notify_member_jump("Member is no longer available")
            return False
        try:
            refilter(refresh_content_index=False)
        except TypeError:
            refilter()

        target_idx = next(
            (
                idx
                for idx, agent in enumerate(self._agents)
                if agent.identity == target_identity
            ),
            None,
        )
        if target_idx is None:
            self._notify_member_jump("Member roster changed; jump cancelled")
            return False
        panel_context = self._target_panel_context(target_idx)
        if panel_context is None:
            self._notify_member_jump("Member is no longer visible")
            return False
        target_panel_idx, panel_key = panel_context

        groups_changed = self._expand_target_groups(target_idx, panel_key)
        if not self._target_is_visible_in_panel(target_idx, panel_key):
            self._notify_member_jump("Member is no longer visible")
            return False
        expand_panel = getattr(self, "_expand_agent_panel", None)
        panel_changed = bool(callable(expand_panel) and expand_panel(panel_key))
        panel_group = getattr(self, "_panel_group", None)
        focus_changed = False
        if panel_group is not None and target_panel_idx is not None:
            focus_changed = target_panel_idx != panel_group.focused_idx
            panel_group.focused_idx = target_panel_idx

        old_idx = self.current_idx
        old_group_key = getattr(self, "_current_group_key", None)
        old_agent = (
            self._agents[old_idx]
            if old_group_key is None and 0 <= old_idx < len(self._agents)
            else None
        )
        if old_agent is not None and old_idx != target_idx:
            arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
            if callable(arm_manual):
                arm_manual(old_agent)

        self._current_group_key = None  # type: ignore[attr-defined]
        self.current_idx = target_idx
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None
        target_agent = self._agents[target_idx]
        acknowledge = getattr(self, "_acknowledge_agent_unread", None)
        if callable(acknowledge):
            acknowledge(target_agent)

        if (
            old_idx == target_idx
            or old_group_key is not None
            or panel_changed
            or groups_changed
            or focus_changed
        ):
            refresh = getattr(self, "_refresh_agents_display", None)
            if callable(refresh):
                try:
                    refresh(list_changed=True, defer_detail=True)
                except TypeError:
                    refresh(list_changed=True)
        return True


__all__ = ["MemberJumpNavigationMixin"]
