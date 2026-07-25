"""Digit-key navigation for numbered tribe, clan, and family rosters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol

from textual.screen import ModalScreen

from ...models.agent import Agent, AgentType
from ...models.agent_family_members import concrete_family_member_rows
from ...models.agent_hoods import agent_owns_lane
from ...models.agent_tribe_summary import AgentPanelFocus
from ._agent_reveal import (
    AgentRevealFailure,
    prepare_agent_navigation_target,
    reveal_agent_navigation_target,
)
from ._types import NavigationMixinBase

if TYPE_CHECKING:
    from ...widgets.prompt_panel._member_roster import (
        MemberJumpContainerIdentity,
        MemberJumpMap,
    )

type MemberIdentity = tuple[AgentType, str, str | None]
type SelectedMemberJumpContainer = Agent | AgentPanelFocus


class _MemberJumpTargetLike(Protocol):
    """Structural jump-target view kept local to navigation."""

    @property
    def number(self) -> str: ...

    @property
    def member_identity(self) -> MemberIdentity: ...

    @property
    def role(self) -> Literal["member", "neighbor", "dismissed"]: ...


class MemberJumpNavigationMixin(NavigationMixinBase):
    """Handle the fixed digit hints rendered in container member rosters."""

    def _selected_member_jump_container(
        self,
    ) -> SelectedMemberJumpContainer | None:
        """Return the selected tribe, clan, or family roster container."""
        if self.current_tab != "agents":
            return None
        for resolver_name in (
            "_resolve_focused_panel",
            "_resolve_focused_collapsed_panel",
        ):
            resolver = getattr(self, resolver_name, None)
            focus = resolver() if callable(resolver) else None
            if focus is not None:
                return focus
        if getattr(self, "_current_group_key", None) is not None:
            return None
        get_selected = getattr(self, "_get_selected_agent", None)
        if not callable(get_selected):
            return None
        agent = get_selected()
        if agent is None or not (agent.is_clan_container or agent_owns_lane(agent)):
            return None
        return agent

    def _member_jump_container_identity(
        self,
        container: SelectedMemberJumpContainer,
    ) -> MemberJumpContainerIdentity:
        """Return the registry key shared by a selected container and map."""
        if isinstance(container, Agent):
            return container.identity
        return container.container_identity

    def _member_jump_map_for(
        self,
        container: SelectedMemberJumpContainer,
    ) -> MemberJumpMap | None:
        """Return only a map that belongs to the live selected container."""
        identity = self._member_jump_container_identity(container)
        jump_map = getattr(self, "_member_jump_maps", {}).get(identity)
        if jump_map is None or jump_map.container_identity != identity:
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
        container: SelectedMemberJumpContainer,
        target: _MemberJumpTargetLike,
    ) -> bool:
        """Reject maps whose target no longer belongs to the container."""
        target_identity = target.member_identity
        if target.role == "neighbor":
            if not isinstance(container, Agent):
                return False
            index_resolver = getattr(self, "_agent_neighbor_index", None)
            if not callable(index_resolver):
                return False
            return target_identity in index_resolver().related_target_identities_for(
                container.identity
            )
        if target.role == "dismissed":
            if not isinstance(container, Agent):
                return False
            dismissed_resolver = getattr(self, "_dismissed_descendant_agents", None)
            if not callable(dismissed_resolver):
                return False
            return any(
                agent.identity == target_identity
                for agent in dismissed_resolver(container)
            )
        if target.role != "member":
            return False
        if not isinstance(container, Agent):
            from ...models._agent_tree import agent_is_tree_child

            panel_index = getattr(self, "_agent_panel_index", None)
            if callable(panel_index):
                agents = panel_index().slice_for(container.panel_key).agents
            else:
                agents = getattr(self, "_agents_in_focused_panel", lambda: [])()
            return any(
                agent.identity == target_identity and not agent_is_tree_child(agent)
                for agent in agents
            )
        if container.is_clan_container:
            return any(
                member.identity == target_identity
                for member in container.runtime_children
                if not member.is_clan_container
            )
        return any(
            member.identity == target_identity
            for member in concrete_family_member_rows(container)
        )

    def _member_jump_target(
        self,
        container: SelectedMemberJumpContainer,
        jump_map: MemberJumpMap,
        number: str,
    ) -> _MemberJumpTargetLike | None:
        """Resolve and revalidate one visible number from a published map."""
        target = next(
            (target for target in jump_map.targets if target.number == number),
            None,
        )
        if target is None:
            self._notify_member_jump(f"No member {number}")
            return None
        if not self._current_member_target_is_valid(container, target):
            subject = "Member roster" if target.role == "member" else "Neighbor list"
            self._notify_member_jump(f"{subject} changed; jump cancelled")
            return None
        return target

    def _activate_member_jump_target(self, target: _MemberJumpTargetLike) -> None:
        """Jump to a current target, or revive a dismissed neighbor."""
        if target.role != "dismissed":
            self._reveal_agent_row(target.member_identity)
            return

        dismissed_resolver = getattr(self, "_active_dismissed_agent_objects", None)
        revive = getattr(self, "_do_revive_agent", None)
        if not callable(dismissed_resolver) or not callable(revive):
            return
        dismissed = next(
            (
                agent
                for agent in dismissed_resolver()
                if agent.identity == target.member_identity
            ),
            None,
        )
        if dismissed is not None:
            revive(dismissed)

    def _handle_member_jump_key(self, key: str) -> bool:
        """Handle a digit, pending second digit, or pending cancellation.

        A non-digit key while pending clears the buffer and returns ``False``
        so Textual can process that key normally.
        """
        if isinstance(getattr(self, "screen", None), ModalScreen):
            self._cancel_member_jump_pending(refresh_footer=False)
            return False

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
            if (
                container is None
                or self._member_jump_container_identity(container) != pending_container
            ):
                self._notify_member_jump("Member selection changed; jump cancelled")
                self._refresh_member_jump_footer_after_action()
                return True
            jump_map = self._member_jump_map_for(container)
            if jump_map is None:
                self._notify_member_jump("Member roster changed; jump cancelled")
                self._refresh_member_jump_footer_after_action()
                return True
            target = self._member_jump_target(
                container,
                jump_map,
                f"{pending_digit}{key}",
            )
            if target is not None:
                self._activate_member_jump_target(target)
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
            self._member_jump_pending_container_identity = (  # type: ignore[attr-defined]
                self._member_jump_container_identity(container)
            )
            self._update_member_jump_footer(key)
            return True

        target = self._member_jump_target(container, jump_map, key)
        if target is not None:
            self._activate_member_jump_target(target)
        return True

    def _refresh_member_jump_footer_after_action(self) -> None:
        """Restore normal footer bindings after a completed/cancelled number."""
        refresh = getattr(self, "_refresh_agent_footer_bindings_only", None)
        if callable(refresh):
            refresh()

    def _reveal_agent_row(self, target_identity: MemberIdentity) -> bool:
        """Reveal a roster target through folds, then select it by identity."""
        plan, failure = prepare_agent_navigation_target(
            self,
            target_identity,
            require_current=False,
        )
        if plan is None:
            self._notify_member_reveal_failure(failure)
            return False

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
        save_anchor = getattr(self, "_save_agents_jump_anchor", None)
        if callable(save_anchor):
            save_anchor()

        outcome = reveal_agent_navigation_target(self, plan)
        reveal = outcome.result
        if reveal is None:
            self._restore_member_jump_history(back_stack, forward_stack)
            self._notify_member_reveal_failure(outcome.failure)
            return False
        if old_agent is not None and reveal.tree_changed:
            rebase_anchor = getattr(self, "_rebase_latest_agents_jump_anchor", None)
            if callable(rebase_anchor):
                rebase_anchor(old_agent.identity)

        panel_group = getattr(self, "_panel_group", None)
        focus_changed = False
        if panel_group is not None:
            focus_changed = reveal.panel_idx != panel_group.focused_idx
            panel_group.focused_idx = reveal.panel_idx

        # A member jump always descends into the target row, including from an
        # explicitly selected expanded panel.
        self._expanded_panel_focus = False  # type: ignore[attr-defined]

        if old_agent is not None and old_agent.identity != target_identity:
            arm_manual = getattr(self, "_arm_manual_unread_after_departure", None)
            if callable(arm_manual):
                arm_manual(old_agent)

        self._current_group_key = None  # type: ignore[attr-defined]
        self.current_idx = reveal.target_idx
        if hasattr(self, "current_attempt_number"):
            self.current_attempt_number = None
        acknowledge = getattr(self, "_acknowledge_agent_unread", None)
        if callable(acknowledge):
            acknowledge(reveal.target_agent)

        if (
            (old_agent is not None and old_agent.identity == target_identity)
            or old_group_key is not None
            or reveal.structural_changed
            or focus_changed
        ):
            refresh = getattr(self, "_refresh_agents_display", None)
            if callable(refresh):
                try:
                    refresh(list_changed=True, defer_detail=True)
                except TypeError:
                    refresh(list_changed=True)
        return True

    def _restore_member_jump_history(
        self,
        back_stack: list[object],
        forward_stack: list[object],
    ) -> None:
        """Undo the tentative history save when reveal application fails."""
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

    def _notify_member_reveal_failure(
        self,
        failure: AgentRevealFailure | None,
    ) -> None:
        """Preserve the member-jump notification contract after extraction."""
        if failure in {
            AgentRevealFailure.TARGET_MISSING,
            AgentRevealFailure.TARGET_AMBIGUOUS,
            AgentRevealFailure.TARGET_FILTERED,
        }:
            self._notify_member_jump("Member roster changed; jump cancelled")
        elif failure in {
            AgentRevealFailure.PANEL_MISSING,
            AgentRevealFailure.TARGET_NOT_VISIBLE,
        }:
            self._notify_member_jump("Member is no longer visible")
        else:
            self._notify_member_jump("Member is no longer available")


__all__ = ["MemberJumpNavigationMixin"]
