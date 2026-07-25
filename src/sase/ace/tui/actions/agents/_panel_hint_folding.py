"""Tribe-scoped single-key folding for visible Agents-tab fold owners."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._panel_fold_intent import effective_panel_collapses, panel_is_collapsed

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent_group_fold import AgentGroupFoldRegistry, GroupKey
    from ...models.agent_panels import AgentPanelGroup, PanelKey
    from ...models.fold_state import FoldStateManager
    from ..navigation.jump_hints import BannerJumpTarget

type GroupFoldHintTarget = tuple[Literal["group"], "PanelKey", "GroupKey"]
type AgentFoldHintTarget = tuple[Literal["agent"], "PanelKey", int, str]
type FoldHintTarget = GroupFoldHintTarget | AgentFoldHintTarget


class AgentPanelHintFoldingMixin:
    """Hint and toggle one fold inside the selected tribe panel."""

    current_tab: str
    _agents: list[Agent]
    _fold_counts: dict[str, tuple[int, int]]
    _fold_manager: FoldStateManager
    _group_fold_registry: AgentGroupFoldRegistry
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool
    _panel_fold_hint_mode_active: bool
    _panel_fold_hint_snapshot: tuple[FoldHintTarget, ...]
    _panel_fold_hint_to_target: dict[str, FoldHintTarget]
    _panel_fold_target_to_hint: dict[FoldHintTarget, str]
    _panel_fold_hint_pending_prefix: str

    def action_toggle_selected_agent_panels(self) -> None:
        """Hint one fold in the selected tribe for immediate toggling."""
        if self.current_tab != "agents":
            return

        hint_bar_active = getattr(self, "_hint_input_bar_active", None)
        if callable(hint_bar_active) and hint_bar_active():
            return
        if getattr(self, "_panel_fold_hint_mode_active", False):
            self._teardown_panel_fold_hint_mode()

        targets = self._enumerate_panel_fold_hint_targets()
        if not targets:
            focused_key = getattr(self._panel_group, "focused_key", None)
            message = (
                "Selected tribe panel is collapsed"
                if panel_is_collapsed(self, focused_key)
                else "No folds in the selected tribe"
            )
            self.notify(message, severity="warning")  # type: ignore[attr-defined]
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
        self._panel_fold_hint_mode_active = True

        self._refresh_panel_fold_hint_display()

        from ...widgets import KeybindingFooter

        try:
            footer = self.query_one(  # type: ignore[attr-defined]
                "#keybinding-footer", KeybindingFooter
            )
            footer.update_fold_hint_bindings()
        except Exception:
            pass

    def _enumerate_panel_fold_hint_targets(self) -> tuple[FoldHintTarget, ...]:
        """Return visible fold owners in the selected tribe's render order."""
        from ...models._agent_tree import agent_fold_key
        from ...models.agent_groups import GroupingMode, build_agent_tree
        from ...models.agent_panels import AgentPanelGroup
        from ._fold_scope import panel_fold_registry
        from ._navigation_order import rendered_panel_slice

        panel_group = getattr(self, "_panel_group", None)
        focused_key = getattr(panel_group, "focused_key", None)
        live_panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key,
            merge_tribe_panels=bool(getattr(self, "_agent_panels_grouped", False)),
            collapsed_panel_keys=effective_panel_collapses(self),
        )
        panel_keys = tuple(live_panel_group.panel_keys)
        if not panel_keys or focused_key not in panel_keys:
            return ()
        if panel_is_collapsed(self, focused_key):
            return ()

        fold_counts = getattr(self, "_fold_counts", {})
        mode: GroupingMode = getattr(self, "_grouping_mode", GroupingMode.STANDARD)
        targets: list[FoldHintTarget] = []
        seen_actions: set[tuple[object, ...]] = set()
        registry = panel_fold_registry(self, focused_key)
        global_indices, panel_agents = rendered_panel_slice(self, focused_key)
        tree = build_agent_tree(panel_agents, fold_registry=registry, mode=mode)
        for entry in tree:
            if entry.kind == "group" and entry.group is not None:
                action = ("group", focused_key, entry.group.group_key)
                if action in seen_actions:
                    continue
                seen_actions.add(action)
                targets.append(("group", focused_key, entry.group.group_key))
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
            agent_action = ("agent-fold", fold_key)
            if agent_action in seen_actions:
                continue
            seen_actions.add(agent_action)
            targets.append(("agent", focused_key, global_indices[local_idx], fold_key))

        return tuple(targets)

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
            else:
                agent_hints[target[2]] = hint
        return agent_hints, banner_hints

    def _refresh_panel_fold_hint_display(self) -> None:
        """Repaint fold chips through the selective focused-panel path."""
        panel_group = getattr(self, "_panel_group", None)
        refresh_affected = getattr(self, "_refresh_affected_panel_widgets", None)
        if (
            panel_group is not None
            and callable(refresh_affected)
            and hasattr(self, "query_one")
        ):
            focused_key = getattr(panel_group, "focused_key", None)
            if focused_key in getattr(
                panel_group, "panel_keys", ()
            ) and refresh_affected({focused_key}):
                return
        self._refresh_agents_display(list_changed=True)  # type: ignore[attr-defined]

    def _teardown_panel_fold_hint_mode(self, *, refresh_titles: bool = True) -> None:
        """Clear the tribe-scoped fold-hint snapshot and transient chips."""
        if not getattr(self, "_panel_fold_hint_mode_active", False):
            return

        self._panel_fold_hint_mode_active = False
        self._panel_fold_hint_snapshot = ()
        self._panel_fold_hint_to_target = {}
        self._panel_fold_target_to_hint = {}
        self._panel_fold_hint_pending_prefix = ""

        if refresh_titles and self.current_tab == "agents":
            self._refresh_panel_fold_hint_display()
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

    def _apply_panel_fold_hint_target(self, target: FoldHintTarget) -> None:
        """Toggle one fold target after verifying the rendered snapshot."""
        snapshot = tuple(getattr(self, "_panel_fold_hint_snapshot", ()))
        live_targets = self._enumerate_panel_fold_hint_targets()
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
        if target[0] == "group":
            panel_key, group_key = target[1], target[2]
            registry = panel_fold_registry(self, panel_key)
            if registry.is_collapsed(group_key):
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
                if not panel_is_collapsed(self, panel_key):
                    snap_group_focus = getattr(
                        self, "_snap_focus_after_group_fold_change", None
                    )
                    if callable(snap_group_focus):
                        snap_group_focus()
        else:
            fold_key = target[3]
            if self._fold_manager.get(fold_key) == FoldLevel.COLLAPSED:
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


__all__ = ["AgentPanelHintFoldingMixin", "FoldHintTarget"]
