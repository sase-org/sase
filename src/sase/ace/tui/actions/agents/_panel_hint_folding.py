"""Tribe-scoped and all-tribe single-key folding for visible Agents-tab folds."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._panel_fold_intent import effective_panel_collapses, panel_is_collapsed

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry, GroupKey
    from ...models.agent_panels import AgentPanelGroup, PanelKey
    from ...models.fold_state import FoldStateManager
    from ..navigation.jump_hints import BannerJumpTarget, PanelJumpTarget

type GroupFoldHintTarget = tuple[Literal["group"], "PanelKey", "GroupKey"]
type AgentFoldHintTarget = tuple[Literal["agent"], "PanelKey", int, str]
type PanelFoldHintTarget = tuple[Literal["panel"], "PanelKey"]
type FoldHintTarget = GroupFoldHintTarget | AgentFoldHintTarget | PanelFoldHintTarget
type FoldHintScope = Literal["tribe", "all"]


class AgentPanelHintFoldingMixin:
    """Hint and toggle or collapse one fold in the selected tribe, or every tribe."""

    current_tab: str
    current_idx: int
    _agents: list[Agent]
    _fold_counts: dict[str, tuple[int, int]]
    _fold_manager: FoldStateManager
    _group_fold_registry: AgentGroupFoldRegistry
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool
    _panel_fold_hint_mode_active: bool
    _panel_fold_hint_intent: Literal["toggle", "collapse"]
    _panel_fold_hint_scope: FoldHintScope
    _panel_fold_hint_snapshot: tuple[FoldHintTarget, ...]
    _panel_fold_hint_to_target: dict[str, FoldHintTarget]
    _panel_fold_target_to_hint: dict[FoldHintTarget, str]
    _panel_fold_hint_pending_prefix: str

    def action_toggle_selected_agent_panels(self) -> None:
        """Hint one fold in the selected tribe for immediate toggling."""
        self._arm_panel_fold_hint_mode(intent="toggle")

    def action_collapse_fold_by_hint(self) -> None:
        """Hint-collapse one fold: focused tribe from a row, every tribe from a panel."""
        if self.current_tab != "agents":
            return
        resolve_panel = getattr(self, "_resolve_focused_panel", None)
        panel_focus = resolve_panel() if callable(resolve_panel) else None
        scope: FoldHintScope = "all" if panel_focus is not None else "tribe"
        self._arm_panel_fold_hint_mode(intent="collapse", scope=scope)

    def _arm_panel_fold_hint_mode(
        self,
        *,
        intent: Literal["toggle", "collapse"],
        scope: FoldHintScope = "tribe",
    ) -> None:
        """Hint fold owners in the selected tribe, or every tribe, for one pick."""
        if self.current_tab != "agents":
            return
        if scope == "all" and intent != "collapse":
            scope = "tribe"

        hint_bar_active = getattr(self, "_hint_input_bar_active", None)
        if callable(hint_bar_active) and hint_bar_active():
            return
        if getattr(self, "_panel_fold_hint_mode_active", False):
            self._teardown_panel_fold_hint_mode()

        collapsible_only = intent == "collapse"
        targets = self._enumerate_panel_fold_hint_targets(
            collapsible_only=collapsible_only,
            scope=scope,
        )
        if not targets:
            self._notify_empty_panel_fold_hint_targets(
                intent=intent,
                scope=scope,
                collapsible_only=collapsible_only,
            )
            return

        # A row or banner must never carry both the apostrophe jump namespace
        # and the fold-selection namespace.
        if getattr(self, "_entry_jump_mode_active", False):
            self._exit_entry_jump_mode()  # type: ignore[attr-defined]

        from ..navigation.jump_hints import build_jump_hint_maps

        hint_to_target, target_to_hint = build_jump_hint_maps(list(targets))
        self._panel_fold_hint_snapshot = targets
        self._panel_fold_hint_to_target = hint_to_target
        self._panel_fold_target_to_hint = target_to_hint
        self._panel_fold_hint_pending_prefix = ""
        self._panel_fold_hint_intent = intent
        self._panel_fold_hint_scope = scope
        self._panel_fold_hint_mode_active = True

        self._refresh_panel_fold_hint_display()

        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one(  # type: ignore[attr-defined]
                "#keybinding-footer", KeybindingFooter
            )
            footer.update_fold_hint_bindings(
                collapse_only=collapsible_only,
                all_tribes=scope == "all",
            )
        except Exception:
            pass

    def _notify_empty_panel_fold_hint_targets(
        self,
        *,
        intent: Literal["toggle", "collapse"],
        scope: FoldHintScope,
        collapsible_only: bool,
    ) -> None:
        """Warn when a hint-picker arm found nothing to offer."""
        del intent
        if scope == "all":
            live_panel_group = self._live_hint_panel_group()
            live_keys = tuple(live_panel_group.panel_keys)
            collapsed = effective_panel_collapses(self, live_keys)
            if live_keys and all(key in collapsed for key in live_keys):
                message = "All tribe panels are collapsed"
            else:
                message = "No expanded folds in any tribe panel"
        else:
            focused_key = getattr(self._panel_group, "focused_key", None)
            if panel_is_collapsed(self, focused_key):
                message = (
                    "Panel is already collapsed"
                    if collapsible_only
                    else "Selected tribe panel is collapsed"
                )
            elif collapsible_only:
                message = "No expanded folds in the selected tribe"
            else:
                message = "No folds in the selected tribe"
        self.notify(message, severity="warning")  # type: ignore[attr-defined]

    def _live_hint_panel_group(self) -> AgentPanelGroup:
        """Return the current live panel group used by fold-hint enumeration."""
        from ...models.agent_panels import AgentPanelGroup

        panel_group = getattr(self, "_panel_group", None)
        focused_key = getattr(panel_group, "focused_key", None)
        return AgentPanelGroup.from_agents(
            self._agents,
            focused_key,
            merge_tribe_panels=bool(getattr(self, "_agent_panels_grouped", False)),
            collapsed_panel_keys=effective_panel_collapses(self),
        )

    def _enumerate_panel_fold_hint_targets(
        self,
        *,
        collapsible_only: bool = False,
        scope: FoldHintScope = "tribe",
    ) -> tuple[FoldHintTarget, ...]:
        """Return visible fold owners in render order for the requested scope.

        With ``collapsible_only``, folds that are already collapsed are
        left out, restricting the hint alphabet to folds ``H`` / ``,H`` can
        collapse.
        """
        live_panel_group = self._live_hint_panel_group()
        panel_keys = tuple(live_panel_group.panel_keys)
        seen_actions: set[tuple[object, ...]] = set()
        if scope == "all":
            targets: list[FoldHintTarget] = []
            offer_panel_titles = (
                not bool(getattr(self, "_agent_panels_grouped", False))
                and len(panel_keys) >= 2
            )
            for panel_key in panel_keys:
                if panel_is_collapsed(self, panel_key):
                    continue
                if offer_panel_titles:
                    targets.append(("panel", panel_key))
                targets.extend(
                    self._panel_fold_hint_targets_for(
                        panel_key,
                        collapsible_only=collapsible_only,
                        seen_actions=seen_actions,
                    )
                )
            return tuple(targets)

        focused_key = getattr(self._panel_group, "focused_key", None)
        if not panel_keys or focused_key not in panel_keys:
            return ()
        if panel_is_collapsed(self, focused_key):
            return ()
        return tuple(
            self._panel_fold_hint_targets_for(
                focused_key,
                collapsible_only=collapsible_only,
                seen_actions=seen_actions,
            )
        )

    def _panel_fold_hint_targets_for(
        self,
        panel_key: PanelKey,
        *,
        collapsible_only: bool,
        seen_actions: set[tuple[object, ...]],
    ) -> list[FoldHintTarget]:
        """Return banner and agent-fold owners for one panel in render order."""
        from ...models._agent_tree import agent_fold_key
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ...models.fold_state import FoldLevel
        from ._fold_scope import panel_fold_registry
        from ._navigation_order import rendered_panel_slice

        fold_counts = getattr(self, "_fold_counts", {})
        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        targets: list[FoldHintTarget] = []
        registry = panel_fold_registry(self, panel_key)
        global_indices, panel_agents = rendered_panel_slice(self, panel_key)
        tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
        for entry in tree:
            if entry.kind == "group" and entry.group is not None:
                group_key = entry.group.group_key
                if collapsible_only and registry.is_collapsed(group_key):
                    continue
                action = ("group", panel_key, group_key)
                if action in seen_actions:
                    continue
                seen_actions.add(action)
                targets.append(("group", panel_key, group_key))
                continue
            if entry.kind != "agent" or entry.agent_idx is None:
                continue
            local_idx = entry.agent_idx
            if not (0 <= local_idx < len(panel_agents)):
                continue
            owner = panel_agents[local_idx]
            # Workflow step rows are controlled by their parent's fold.
            # Family/clan member rows may still own a distinct nested fold.
            if owner.is_workflow_step_child:
                continue
            fold_key = agent_fold_key(owner)
            if fold_key is None or (
                not owner.is_clan_container and fold_key not in fold_counts
            ):
                continue
            if (
                collapsible_only
                and self._fold_manager.get(fold_key) == FoldLevel.COLLAPSED
            ):
                continue
            agent_action = ("agent-fold", fold_key)
            if agent_action in seen_actions:
                continue
            seen_actions.add(agent_action)
            targets.append(("agent", panel_key, global_indices[local_idx], fold_key))
        return targets

    def _panel_fold_hint_display_maps(
        self,
    ) -> tuple[
        dict[int, str],
        dict[BannerJumpTarget, str],
    ]:
        """Project fold targets onto the row and banner hint channels."""
        panel_indices = {
            key: idx
            for idx, key in enumerate(getattr(self._panel_group, "panel_keys", ()))
        }
        agent_hints: dict[int, str] = {}
        banner_hints: dict[BannerJumpTarget, str] = {}
        for target, hint in getattr(self, "_panel_fold_target_to_hint", {}).items():
            if target[0] == "group":
                panel_idx = panel_indices.get(target[1])
                if panel_idx is not None:
                    banner_hints[("banner", panel_idx, target[2])] = hint
            elif target[0] == "agent":
                agent_hints[target[2]] = hint
        return agent_hints, banner_hints

    def _panel_fold_hint_title_map(self) -> dict[PanelJumpTarget, str]:
        """Project panel-title fold targets onto the title-chip channel."""
        title_hints: dict[PanelJumpTarget, str] = {}
        for target, hint in getattr(self, "_panel_fold_target_to_hint", {}).items():
            if target[0] == "panel":
                title_hints[("panel", target[1])] = hint
        return title_hints

    def _active_panel_title_jump_hints(self) -> dict[PanelJumpTarget, str] | None:
        """Return the live title-chip map for jump mode or fold-hint mode."""
        if getattr(self, "_entry_jump_mode_active", False):
            hints = dict(getattr(self, "_entry_jump_panel_to_hint", {}))
            return hints or None
        if getattr(self, "_panel_fold_hint_mode_active", False):
            return self._panel_fold_hint_title_map() or None
        return None

    def _panel_fold_hint_affected_keys(self) -> set[PanelKey]:
        """Return panel keys whose chips must be painted or cleared."""
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return set()
        panel_keys = getattr(panel_group, "panel_keys", ())
        if getattr(self, "_panel_fold_hint_scope", "tribe") == "all":
            return set(panel_keys)
        focused_key = getattr(panel_group, "focused_key", None)
        if focused_key in panel_keys:
            return {focused_key}
        return set()

    def _refresh_panel_fold_hint_display(
        self, affected_keys: set[PanelKey] | None = None
    ) -> None:
        """Repaint fold chips through the selective affected-panel path."""
        panel_group = getattr(self, "_panel_group", None)
        refresh_affected = getattr(self, "_refresh_affected_panel_widgets", None)
        if (
            panel_group is not None
            and callable(refresh_affected)
            and hasattr(self, "query_one")
        ):
            keys = (
                affected_keys
                if affected_keys is not None
                else self._panel_fold_hint_affected_keys()
            )
            if keys and refresh_affected(keys):
                return
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

    def _teardown_panel_fold_hint_mode(self, *, refresh_titles: bool = True) -> None:
        """Clear the fold-hint snapshot and transient chips."""
        if not getattr(self, "_panel_fold_hint_mode_active", False):
            return

        affected_keys = self._panel_fold_hint_affected_keys()
        self._panel_fold_hint_mode_active = False
        self._panel_fold_hint_snapshot = ()
        self._panel_fold_hint_to_target = {}
        self._panel_fold_target_to_hint = {}
        self._panel_fold_hint_pending_prefix = ""
        self._panel_fold_hint_intent = "toggle"
        self._panel_fold_hint_scope = "tribe"

        if refresh_titles and self.current_tab == "agents":
            self._refresh_panel_fold_hint_display(affected_keys)
            refresh_footer = getattr(self, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh_footer):
                refresh_footer()

    def _handle_panel_fold_hint_key(self, key: str) -> bool:
        """Consume one adaptive fold-hint key while the mode is armed."""
        if not getattr(self, "_panel_fold_hint_mode_active", False):
            return False
        if key == "escape":
            self._teardown_panel_fold_hint_mode()
            return True

        from ..navigation.jump_hints import JumpHintMatchOutcome, match_jump_hint

        match = match_jump_hint(
            self._panel_fold_hint_to_target,
            self._panel_fold_hint_pending_prefix,
            key,
        )
        if match.outcome is JumpHintMatchOutcome.PENDING:
            self._panel_fold_hint_pending_prefix = match.prefix
            return True
        if match.outcome is JumpHintMatchOutcome.INVALID:
            self._teardown_panel_fold_hint_mode()
            return True

        self._panel_fold_hint_pending_prefix = ""
        if match.target is not None:
            self._apply_panel_fold_hint_target(match.target)
        else:
            self._teardown_panel_fold_hint_mode()
        return True

    def _selected_row_hidden_by_fold(self, fold_key: str) -> bool:
        """Return whether collapsing ``fold_key`` would hide the selected row."""
        if not (0 <= self.current_idx < len(self._agents)):
            return False

        from ...models._agent_tree import (
            agent_fold_key,
            agent_gating_fold_key,
            agent_parent_fold_key,
            tree_parent_lookup,
        )
        from ._folding_clans import selected_enclosing_clan_fold_key

        selected = self._agents[self.current_idx]
        if agent_fold_key(selected) == fold_key:
            return False
        if selected_enclosing_clan_fold_key(self._agents, self.current_idx) == fold_key:
            return True

        lookup = tree_parent_lookup(self._agents)
        current = selected
        visited: set[int] = set()
        while True:
            parent_key = (
                agent_gating_fold_key(current, lookup)
                if current.is_monitor or current.is_gate
                else agent_parent_fold_key(current)
            )
            if parent_key is None:
                return False
            parent = lookup.get(parent_key)
            if parent is None:
                return parent_key == fold_key
            parent_id = id(parent)
            if parent_id in visited:
                return False
            visited.add(parent_id)
            if agent_fold_key(parent) == fold_key:
                return True
            current = parent

    def _apply_panel_fold_hint_target(self, target: FoldHintTarget) -> None:
        """Toggle or collapse one fold target after verifying the snapshot."""
        intent = getattr(self, "_panel_fold_hint_intent", "toggle")
        scope: FoldHintScope = "tribe"
        if getattr(self, "_panel_fold_hint_scope", "tribe") == "all":
            scope = "all"
        collapsible_only = intent == "collapse"
        snapshot = tuple(getattr(self, "_panel_fold_hint_snapshot", ()))
        live_targets = self._enumerate_panel_fold_hint_targets(
            collapsible_only=collapsible_only,
            scope=scope,
        )
        if snapshot != live_targets or target not in live_targets:
            self._teardown_panel_fold_hint_mode()
            self.notify(  # type: ignore[attr-defined]
                "Visible folds changed; retry fold selection", severity="warning"
            )
            return

        from ...models.fold_state import FoldLevel
        from ._fold_scope import panel_fold_registry

        changed = False
        expanded = False
        agent_fold_changed = False
        reanchored = False
        focused_key = getattr(self._panel_group, "focused_key", None)
        if target[0] == "panel":
            self._apply_panel_fold_hint_panel_target(target[1], focused_key)
            return
        if target[0] == "group":
            panel_key, group_key = target[1], target[2]
            registry = panel_fold_registry(self, panel_key)
            if not collapsible_only and registry.is_collapsed(group_key):
                changed = registry.expand(group_key)
                new_collapsed = False
                expanded = changed
            else:
                changed = registry.collapse(group_key)
                new_collapsed = True
            if changed:
                self._persist_group_fold_change(  # type: ignore[attr-defined]
                    group_key,
                    collapsed=new_collapsed,
                    panel_key=panel_key,
                )
                if panel_key == focused_key and not panel_is_collapsed(self, panel_key):
                    snap_group_focus = getattr(
                        self, "_snap_focus_after_group_fold_change", None
                    )
                    if callable(snap_group_focus):
                        snap_group_focus()
        else:
            fold_key = target[3]
            resolve_panel = getattr(self, "_resolve_focused_panel", None)
            row_focus = not callable(resolve_panel) or resolve_panel() is None
            if row_focus and self._selected_row_hidden_by_fold(fold_key):
                reanchor = getattr(self, "_reanchor_to_fold_owner", None)
                if callable(reanchor):
                    reanchor(fold_key)
                    reanchored = True
            if (
                not collapsible_only
                and self._fold_manager.get(fold_key) == FoldLevel.COLLAPSED
            ):
                changed = self._fold_manager.expand(fold_key)
                expanded = changed
            else:
                while self._fold_manager.get(fold_key) != FoldLevel.COLLAPSED:
                    if not self._fold_manager.collapse(fold_key):
                        break
                    changed = True
            agent_fold_changed = changed

        # Clear chips before the one list repaint that applies the mutation.
        self._teardown_panel_fold_hint_mode(refresh_titles=False)
        self._invalidate_agent_panel_cache()  # type: ignore[attr-defined]
        if agent_fold_changed and callable(getattr(self, "_refilter_agents", None)):
            self._refilter_agents(refresh_content_index=False)  # type: ignore[attr-defined]
            if reanchored:
                remember = getattr(self, "_remember_focused_panel_selection", None)
                if callable(remember):
                    remember()
        else:
            self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

        refresh_footer = getattr(self, "_refresh_agent_footer_bindings_only", None)
        if callable(refresh_footer):
            refresh_footer()

        if changed:
            self.notify(  # type: ignore[attr-defined]
                "Fold expanded" if expanded else "Fold collapsed",
                timeout=1.5,
            )
        else:
            self.notify("No fold change", timeout=1.5)  # type: ignore[attr-defined]

    def _apply_panel_fold_hint_panel_target(
        self,
        panel_key: PanelKey,
        focused_key: PanelKey,
    ) -> None:
        """Collapse one whole panel from an all-tribes title-chip pick."""
        self._teardown_panel_fold_hint_mode(refresh_titles=False)
        if panel_key == focused_key:
            collapse_focused = getattr(self, "_collapse_focused_panel", None)
            if callable(collapse_focused):
                collapse_focused()
        else:
            apply_layout = getattr(self, "_apply_panel_fold_layout", None)
            panel_group = getattr(self, "_panel_group", None)
            if callable(apply_layout) and panel_group is not None:
                live_keys = list(panel_group.panel_keys)
                desired_collapsed = effective_panel_collapses(self, live_keys) | {
                    panel_key
                }
                apply_layout(live_keys, desired_collapsed)
        refresh_footer = getattr(self, "_refresh_agent_footer_bindings_only", None)
        if callable(refresh_footer):
            refresh_footer()
        self.notify("Panel collapsed", timeout=1.5)  # type: ignore[attr-defined]


__all__ = ["AgentPanelHintFoldingMixin", "FoldHintTarget"]
